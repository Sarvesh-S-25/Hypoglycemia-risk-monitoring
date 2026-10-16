// GlucoSentry primary node firmware (bench build).
//
// Sensors: ADS1115 (0x48) reading the AD8232 output on A0, AD8232 lead-off
// on GPIO32/33, MPU6500 (0x68) for motion. Samples ECG at 250 Hz.
//
// Two outputs, both always on:
//  - USB serial: one "ecg_mV,leads_off,ax,ay,az" line per sample, for the
//    backend's GS_SOURCE=serial and the Python plotter.
//  - BLE GATT server per the backend's docs/API_CONTRACT.md section 2.1: one
//    decimated 100 Hz window per second, with on-device SQI.

#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>

// ---- Pins -----------------------------------------------------------------
#define SDA_PIN      21
#define SCL_PIN      22
#define LO_PLUS_PIN  32
#define LO_MINUS_PIN 33
#define LED_PIN      2   // on-board blue LED; stands in for the vibration motor

// ---- I2C devices ------------------------------------------------------------
#define MPU_ADDR 0x68
#define ADS_ADDR 0x48
#define REG_PWR_MGMT_1   0x6B
#define REG_ACCEL_CONFIG 0x1C
#define REG_GYRO_CONFIG  0x1B
#define REG_ACCEL_XOUT_H 0x3B
#define ADS_REG_CONVERSION 0x00
#define ADS_REG_CONFIG     0x01
#define ADS_CONFIG 0x42E3        // continuous, AIN0 vs GND, +-4.096V, 860 SPS
#define ADS_MV_PER_LSB 0.125f
#define ACCEL_SCALE 4096.0f      // LSB per g at +-8g
#define G 9.80665f

// ---- Sampling / windows -------------------------------------------------------
#define DEVICE_RATE_HZ   250
#define SAMPLE_US        (1000000 / DEVICE_RATE_HZ)
#define MPU_EVERY_N      10      // accel at 25 Hz
#define WINDOW_IN        DEVICE_RATE_HZ   // 1 s of input samples
#define OUT_RATE_HZ      100
#define WINDOW_OUT       OUT_RATE_HZ      // 1 s of output samples
#define MOTION_SQI_THRESHOLD_MS2 1.0f     // same rule as the backend serial source

// ---- BLE (UUIDs must match backend app/config.py) ----------------------------
#define DEVICE_NAME        "GlucoSentry-ECG"
#define SERVICE_UUID       "0000a000-0000-1000-8000-00805f9b34fb"
#define CHAR_ECG_DATA      "0000a001-0000-1000-8000-00805f9b34fb"
#define CHAR_SQI_FLAG      "0000a002-0000-1000-8000-00805f9b34fb"
#define CHAR_DEVICE_STATUS "0000a003-0000-1000-8000-00805f9b34fb"
#define CHAR_CONTROLLER    "0000a004-0000-1000-8000-00805f9b34fb"
#define CHAR_ALERT         "0000a005-0000-1000-8000-00805f9b34fb"
#define CHAR_AUX_WAKE      "0000a006-0000-1000-8000-00805f9b34fb"
#define BATTERY_UNKNOWN    255
#define ALERT_BLINK_MS     3000

BLECharacteristic *ecgChar, *sqiChar, *statusChar;
volatile bool bleConnected = false;
volatile uint8_t currentMode = 1;          // 0=Eco 1=Normal 2=Watch 3=Verify
volatile uint32_t alertUntilMs = 0;

// Window buffers (filled at 250 Hz, sent once per second)
int16_t ecgIn[WINDOW_IN];
float accelMag[WINDOW_IN];
bool windowLeadsOff = false;
uint16_t inCount = 0;
double windowStartS = 0;

float ax = 0, ay = 0, az = 0;
bool mpuOk = false, adsOk = false;

// ---- I2C helpers ------------------------------------------------------------
void writeReg8(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

void writeReg16(uint8_t addr, uint8_t reg, uint16_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val >> 8);
  Wire.write(val & 0xFF);
  Wire.endTransmission();
}

bool devicePresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

int16_t readEcgCounts() {
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(ADS_REG_CONVERSION);
  Wire.endTransmission(false);
  if (Wire.requestFrom((uint8_t)ADS_ADDR, (uint8_t)2) != 2) return 0;
  return (int16_t)((Wire.read() << 8) | Wire.read());
}

void readAccel() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_ACCEL_XOUT_H);
  Wire.endTransmission(false);
  if (Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)6) != 6) return;
  int16_t x = (Wire.read() << 8) | Wire.read();
  int16_t y = (Wire.read() << 8) | Wire.read();
  int16_t z = (Wire.read() << 8) | Wire.read();
  ax = x / ACCEL_SCALE * G;
  ay = y / ACCEL_SCALE * G;
  az = z / ACCEL_SCALE * G;
}

// ---- BLE callbacks ------------------------------------------------------------
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *) override { bleConnected = true; }
  void onDisconnect(BLEServer *server) override {
    bleConnected = false;
    server->getAdvertising()->start();  // accept the next connection
  }
};

class ControllerCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    std::string v = c->getValue();
    if (!v.empty() && (uint8_t)v[0] <= 3) currentMode = (uint8_t)v[0];
  }
};

class AlertCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *) override { alertUntilMs = millis() + ALERT_BLINK_MS; }
};

class AuxWakeCallbacks : public BLECharacteristicCallbacks {
  // No auxiliary node on the bench; accepted so the backend's write succeeds.
  void onWrite(BLECharacteristic *) override {}
};

BLECharacteristic *addNotify(BLEService *svc, const char *uuid) {
  BLECharacteristic *c = svc->createCharacteristic(uuid, BLECharacteristic::PROPERTY_NOTIFY);
  c->addDescriptor(new BLE2902());
  return c;
}

void addWrite(BLEService *svc, const char *uuid, BLECharacteristicCallbacks *cb) {
  BLECharacteristic *c = svc->createCharacteristic(
      uuid, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  c->setCallbacks(cb);
}

void setupBle() {
  BLEDevice::init(DEVICE_NAME);
  BLEDevice::setMTU(247);  // a whole 208-byte window per notification
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  // 3 notify chars x 3 handles + 3 write chars x 2 handles + service = 16,
  // above the library's default of 15.
  BLEService *svc = server->createService(BLEUUID(SERVICE_UUID), 32);
  ecgChar = addNotify(svc, CHAR_ECG_DATA);
  sqiChar = addNotify(svc, CHAR_SQI_FLAG);
  statusChar = addNotify(svc, CHAR_DEVICE_STATUS);
  addWrite(svc, CHAR_CONTROLLER, new ControllerCallbacks());
  addWrite(svc, CHAR_ALERT, new AlertCallbacks());
  addWrite(svc, CHAR_AUX_WAKE, new AuxWakeCallbacks());
  svc->start();

  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
}

// ---- Window processing ----------------------------------------------------------
// 250 -> 100 Hz: 3-tap moving average (edge-clamped), then linear
// interpolation onto the 10 ms grid. Mirrors the backend serial source.
void decimate(const int16_t *in, int16_t *out) {
  static float smooth[WINDOW_IN];
  for (int i = 0; i < WINDOW_IN; i++) {
    int a = i > 0 ? i - 1 : 0;
    int b = i < WINDOW_IN - 1 ? i + 1 : WINDOW_IN - 1;
    smooth[i] = (in[a] + in[i] + in[b]) / 3.0f;
  }
  for (int k = 0; k < WINDOW_OUT; k++) {
    float pos = k * (float)DEVICE_RATE_HZ / OUT_RATE_HZ;  // 2.5 input samples per output
    int i0 = (int)pos;
    int i1 = i0 + 1 < WINDOW_IN ? i0 + 1 : i0;
    float f = pos - i0;
    out[k] = (int16_t)lroundf(smooth[i0] * (1 - f) + smooth[i1] * f);
  }
}

float stddev(const float *x, int n) {
  double sum = 0, sq = 0;
  for (int i = 0; i < n; i++) { sum += x[i]; sq += (double)x[i] * x[i]; }
  double mean = sum / n;
  double var = sq / n - mean * mean;
  return var > 0 ? sqrt(var) : 0;
}

void sendWindow() {
  float motion = stddev(accelMag, WINDOW_IN);
  uint8_t sqi = (windowLeadsOff || motion > MOTION_SQI_THRESHOLD_MS2) ? 0 : 1;

  if (!bleConnected) return;

  // Order per contract: sqi_flag, ecg_data, device_status.
  sqiChar->setValue(&sqi, 1);
  sqiChar->notify();

  static uint8_t pkt[8 + WINDOW_OUT * 2];
  memcpy(pkt, &windowStartS, 8);  // ESP32 is little-endian, as the contract requires
  decimate(ecgIn, (int16_t *)(pkt + 8));
  ecgChar->setValue(pkt, sizeof(pkt));
  ecgChar->notify();

  uint16_t motionCenti = (uint16_t)min(65535.0f, motion * 100.0f);
  uint8_t status[5] = {
      BATTERY_UNKNOWN, currentMode, (uint8_t)(windowLeadsOff ? 1 : 0),
      (uint8_t)(motionCenti & 0xFF), (uint8_t)(motionCenti >> 8)};
  statusChar->setValue(status, sizeof(status));
  statusChar->notify();
}

// ---- Setup / loop -------------------------------------------------------------
void setup() {
  Serial.begin(921600);
  delay(500);
  pinMode(LO_PLUS_PIN, INPUT);
  pinMode(LO_MINUS_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  mpuOk = devicePresent(MPU_ADDR);
  adsOk = devicePresent(ADS_ADDR);
  Serial.printf("MPU6500 (0x68): %s\n", mpuOk ? "OK" : "MISSING");
  Serial.printf("ADS1115 (0x48): %s\n", adsOk ? "OK" : "MISSING");
  if (mpuOk) {
    writeReg8(MPU_ADDR, REG_PWR_MGMT_1, 0x00);
    delay(100);
    writeReg8(MPU_ADDR, REG_ACCEL_CONFIG, 0x10);
    writeReg8(MPU_ADDR, REG_GYRO_CONFIG, 0x08);
  }
  if (adsOk) writeReg16(ADS_ADDR, ADS_REG_CONFIG, ADS_CONFIG);

  setupBle();
  Serial.printf("BLE advertising as %s\n", DEVICE_NAME);
  Serial.println("Streaming: ecg_mV,leads_off,ax,ay,az");
}

void loop() {
  static uint32_t nextSample = micros();
  static uint32_t count = 0;

  // Alert: blink the LED at 5 Hz until the deadline; LED off otherwise.
  digitalWrite(LED_PIN, millis() < alertUntilMs ? (millis() / 100) % 2 : LOW);

  if ((int32_t)(micros() - nextSample) < 0) return;
  nextSample += SAMPLE_US;

  bool leadsOff = digitalRead(LO_PLUS_PIN) || digitalRead(LO_MINUS_PIN);
  int16_t counts = (leadsOff || !adsOk) ? 0 : readEcgCounts();
  if (mpuOk && count++ % MPU_EVERY_N == 0) readAccel();

  if (inCount == 0) {
    windowStartS = micros() / 1e6;
    windowLeadsOff = false;
  }
  ecgIn[inCount] = counts;
  accelMag[inCount] = sqrtf(ax * ax + ay * ay + az * az);
  windowLeadsOff |= leadsOff;
  if (++inCount == WINDOW_IN) {
    sendWindow();
    inCount = 0;
  }

  Serial.printf("%.1f,%d,%.2f,%.2f,%.2f\n", counts * ADS_MV_PER_LSB, leadsOff, ax, ay, az);
}
