// GlucoSentry auxiliary node: bilateral foot temperature over BLE, deep
// sleeping between check-ins (docs/API_CONTRACT.md section 2.2).
//
// Cycle:
//   deep sleep (RTC timer, or the BOOT button)
//     -> boot, advertise for up to AWAKE_WINDOW_MS
//     -> host connects, reads `node_info` (why we woke)
//     -> host may write `wake`: power the dividers, read both sides twice,
//        notify `foot_temp_result`, power them down
//     -> host writes `sleep` (uint32 seconds): deep sleep for that long
//   No host within the window, or no `sleep` command in time: deep sleep for
//   FALLBACK_SLEEP_S and try again.
//
// The radio is off in deep sleep, so the node cannot be woken over BLE. The
// host therefore decides at each check-in whether a reading is due, and tells
// the node when to check in next.
//
// Wiring (bench build): GPIO32 -> 1k -> GPIO34 -> NTC left  -> GND
//                       GPIO32 -> 1k -> GPIO35 -> NTC right -> GND
// The thermistors are 100 ohm NTCs (marked 101), hence the 1k fixed resistors.
// GPIO32 powers the dividers only while reading and is held low in deep sleep.
// If the dividers are fed from 3V3 instead, they draw ~6 mA continuously.
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <driver/gpio.h>
#include <esp_sleep.h>

// ---- Pins and thermistor constants -----------------------------------------
#define PWR_PIN     32
#define LEFT_PIN    34
#define RIGHT_PIN   35
#define BUTTON_PIN  GPIO_NUM_0  // the board's BOOT button, active low

const float R_FIXED = 1000.0;
const float R0      = 100.0;    // NTC resistance at 25 C (marking 101)
const float BETA    = 3950.0;   // typical; uncalibrated
const float VREF_MV = 3300.0;

// Plausible skin/room range; anything outside is a wiring or contact fault.
const float T_MIN_C = 10.0;
const float T_MAX_C = 45.0;
// Two reads 100 ms apart must agree this closely or the reading is unstable.
const float STABLE_C = 0.5;

// ---- Sleep timing ------------------------------------------------------------
const uint32_t AWAKE_WINDOW_MS   = 20000;  // advertise this long waiting for the host
const uint32_t SESSION_LIMIT_MS  = 30000;  // connected but no `sleep` command: give up
const uint32_t FALLBACK_SLEEP_S  = 60;     // host absent: try again after this
const uint32_t MIN_SLEEP_S       = 2;
const uint32_t MAX_SLEEP_S       = 7 * 24 * 3600;

// ---- BLE (UUIDs must match backend app/config.py) ----------------------------
#define DEVICE_NAME       "GlucoSentry-Foot"
#define SERVICE_UUID      "0000b000-0000-1000-8000-00805f9b34fb"
#define CHAR_WAKE         "0000b001-0000-1000-8000-00805f9b34fb"
#define CHAR_FOOT_RESULT  "0000b002-0000-1000-8000-00805f9b34fb"
#define CHAR_SLEEP        "0000b003-0000-1000-8000-00805f9b34fb"
#define CHAR_NODE_INFO    "0000b004-0000-1000-8000-00805f9b34fb"

enum WakeReason : uint8_t { WAKE_POWER_ON = 0, WAKE_TIMER = 1, WAKE_BUTTON = 2 };

// Survive deep sleep (RTC slow memory).
RTC_DATA_ATTR uint32_t bootCount = 0;
RTC_DATA_ATTR uint32_t lastSleepS = 0;

BLECharacteristic *resultChar;
volatile bool wakeRequested = false;
volatile bool sleepRequested = false;
volatile uint32_t sleepSeconds = FALLBACK_SLEEP_S;
volatile bool connected = false;
uint32_t connectedAtMs = 0;

// foot_temp_result payload: <f t_left, <f t_right, <f delta, u8 valid (13 bytes).
struct __attribute__((packed)) FootResult {
  float t_left;
  float t_right;
  float delta;
  uint8_t valid;
};

// node_info payload: u8 wake_reason, <u32 boot_count, <u32 last_sleep_s (9 bytes).
struct __attribute__((packed)) NodeInfo {
  uint8_t wake_reason;
  uint32_t boot_count;
  uint32_t last_sleep_s;
};

float readTempC(int pin) {
  uint32_t sum = 0;
  for (int i = 0; i < 32; i++) sum += analogReadMilliVolts(pin);
  float mv = sum / 32.0;
  if (mv < 20 || mv > 900) return NAN;  // open or shorted divider (0 dB range is ~0-950 mV)
  float r = R_FIXED * mv / (VREF_MV - mv);
  return 1.0 / (1.0 / 298.15 + log(r / R0) / BETA) - 273.15;
}

bool plausible(float t) { return !isnan(t) && t >= T_MIN_C && t <= T_MAX_C; }

FootResult takeReading() {
  digitalWrite(PWR_PIN, HIGH);
  delay(20);
  float l1 = readTempC(LEFT_PIN), r1 = readTempC(RIGHT_PIN);
  delay(100);
  float l2 = readTempC(LEFT_PIN), r2 = readTempC(RIGHT_PIN);
  digitalWrite(PWR_PIN, LOW);

  FootResult res;
  res.t_left = (l1 + l2) / 2;
  res.t_right = (r1 + r2) / 2;
  res.delta = res.t_left - res.t_right;
  res.valid = plausible(l1) && plausible(l2) && plausible(r1) && plausible(r2) &&
              fabs(l1 - l2) < STABLE_C && fabs(r1 - r2) < STABLE_C;
  if (!res.valid) {
    // NaN does not survive JSON on the host side; send zeros with valid=0.
    if (isnan(res.t_left)) res.t_left = 0;
    if (isnan(res.t_right)) res.t_right = 0;
    if (isnan(res.delta)) res.delta = 0;
  }
  return res;
}

void goToSleep(uint32_t seconds) {
  seconds = constrain(seconds, MIN_SLEEP_S, MAX_SLEEP_S);
  lastSleepS = seconds;
  Serial.printf("deep sleep for %lu s\n", (unsigned long)seconds);
  Serial.flush();

  // Keep the dividers unpowered through deep sleep.
  digitalWrite(PWR_PIN, LOW);
  gpio_hold_en((gpio_num_t)PWR_PIN);
  gpio_deep_sleep_hold_en();

  esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  esp_sleep_enable_ext0_wakeup(BUTTON_PIN, 0);
  esp_deep_sleep_start();
}

WakeReason wakeReason() {
  switch (esp_sleep_get_wakeup_cause()) {
    case ESP_SLEEP_WAKEUP_TIMER: return WAKE_TIMER;
    case ESP_SLEEP_WAKEUP_EXT0: return WAKE_BUTTON;
    default: return WAKE_POWER_ON;
  }
}

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *) override {
    connected = true;
    connectedAtMs = millis();
  }
  void onDisconnect(BLEServer *server) override {
    connected = false;
    if (!sleepRequested) server->startAdvertising();
  }
};

// These run in the BLE task: only set flags here, act in loop().
class WakeCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *) override { wakeRequested = true; }
};

class SleepCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    std::string v = c->getValue();
    if (v.size() >= 4) {
      sleepSeconds = (uint8_t)v[0] | ((uint8_t)v[1] << 8) | ((uint8_t)v[2] << 16) | ((uint32_t)(uint8_t)v[3] << 24);
      sleepRequested = true;
    }
  }
};

void setup() {
  Serial.begin(115200);
  bootCount++;
  WakeReason reason = wakeReason();

  gpio_hold_dis((gpio_num_t)PWR_PIN);
  pinMode(PWR_PIN, OUTPUT);
  digitalWrite(PWR_PIN, LOW);
  analogSetAttenuation(ADC_0db);  // ~0-950 mV range: the dividers sit near 300 mV

  BLEDevice::init(DEVICE_NAME);
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  BLEService *svc = server->createService(SERVICE_UUID);

  BLECharacteristic *wake = svc->createCharacteristic(
      CHAR_WAKE, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  wake->setCallbacks(new WakeCallbacks());

  resultChar = svc->createCharacteristic(
      CHAR_FOOT_RESULT, BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ);
  resultChar->addDescriptor(new BLE2902());

  BLECharacteristic *sleepChar = svc->createCharacteristic(CHAR_SLEEP, BLECharacteristic::PROPERTY_WRITE);
  sleepChar->setCallbacks(new SleepCallbacks());

  NodeInfo info = {reason, bootCount, lastSleepS};
  BLECharacteristic *infoChar = svc->createCharacteristic(CHAR_NODE_INFO, BLECharacteristic::PROPERTY_READ);
  infoChar->setValue((uint8_t *)&info, sizeof(info));

  svc->start();
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.printf("GlucoSentry-Foot awake (reason %d, boot %lu), advertising\n", reason, (unsigned long)bootCount);
}

void loop() {
  // Serial "w" triggers a reading too, for bench testing without the host.
  if (Serial.available() && Serial.read() == 'w') wakeRequested = true;

  if (wakeRequested) {
    wakeRequested = false;
    FootResult res = takeReading();
    resultChar->setValue((uint8_t *)&res, sizeof(res));
    if (connected) resultChar->notify();
    Serial.printf("reading: L %.2f C  R %.2f C  delta %.2f C  valid %d\n",
                  res.t_left, res.t_right, res.delta, res.valid);
  }

  if (sleepRequested) {
    delay(300);  // let the write response reach the host before the radio stops
    goToSleep(sleepSeconds);
  }
  if (!connected && millis() > AWAKE_WINDOW_MS) {
    Serial.println("no host in the awake window");
    goToSleep(FALLBACK_SLEEP_S);
  }
  if (connected && millis() - connectedAtMs > SESSION_LIMIT_MS) {
    Serial.println("host connected but never sent sleep");
    goToSleep(FALLBACK_SLEEP_S);
  }
  delay(20);
}
