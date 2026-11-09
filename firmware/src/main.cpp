#include <Arduino.h>
#include <esp_system.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include "ota_config.h"
#include "web_mode.h"
#include <Wire.h>
#include <NimBLEDevice.h>
#include <atomic>
#include <algorithm>
#include <Adafruit_ADS1X15.h>

// GPIO numbers, NOT physical module pad numbers. Change to match your board.
constexpr int SDA_PIN = 5, SCL_PIN = 6, RDY_PIN = 4;
constexpr uint8_t ADC_ADDRESS = 0x48;
constexpr bool DIFFERENTIAL = true; // false: A0-GND; true: A0-A1
constexpr uint32_t SERIAL_BAUD = 460800;
Adafruit_ADS1115 ads;
struct Sample { uint32_t seq, us; int16_t raw; };
QueueHandle_t samples, bleSamples;
constexpr char SERVICE_UUID[] = "c47e1000-17c4-4b56-9be5-125cece00001";
constexpr char DATA_UUID[] = "c47e1001-17c4-4b56-9be5-125cece00001";
std::atomic<bool> subscribed{false};
std::atomic<uint16_t> peerHandle{0}, peerMtu{23};
NimBLECharacteristic *bleData, *bleStatus;
NimBLEServer *bleServer;
bool adcStarted = false;
std::atomic<bool> otaRequested{false};
constexpr char OTA_COMMAND_UUID[] = "c47e1003-17c4-4b56-9be5-125cece00001";
class OtaCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *characteristic, NimBLEConnInfo &) override {
    auto value = characteristic->getValue();
    if (value.size() == strlen(OTA_TOKEN) && !memcmp(value.data(), OTA_TOKEN, value.size())) {
      bleStatus->setValue("OTA_ACCEPTED"); otaRequested=true;
    }
  }
};
const char *startupError = "waiting for ADS1115";
uint32_t bootReason;
RTC_DATA_ATTR uint32_t bleRecoveryRestarts = 0;
uint32_t bleUnhealthySince = 0, bleHealthySince = 0;

// Local stack check, not proof that a remote PC can receive advertisements.
void recoverBle() {
  auto adv = NimBLEDevice::getAdvertising();
  const uint32_t now = millis();
  const bool healthy = bleServer->getConnectedCount() || adv->isAdvertising();
  if (healthy) {
    bleUnhealthySince = 0;
    if (!bleHealthySince) bleHealthySince = now;
    if (now - bleHealthySince > 60000) bleRecoveryRestarts = 0;
    return;
  }
  bleHealthySince = 0;
  if (!bleUnhealthySince) bleUnhealthySince = now;
  adv->start();
  if (now - bleUnhealthySince >= 10000 && bleRecoveryRestarts < 2) {
    ++bleRecoveryRestarts;
    ESP.restart(); // software restart; not an external EN/RTS pulse
  }
}
// Never print unconditionally during startup: no serial host is required.
void serialTryLine(const char *line) {
  const size_t n = strlen(line);
  if (Serial && size_t(Serial.availableForWrite()) >= n) {
    Serial.write(reinterpret_cast<const uint8_t *>(line), n);
  }
}
class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer *server, NimBLEConnInfo &info) override {
    peerHandle = info.getConnHandle(); peerMtu = info.getMTU();
    server->updateConnParams(info.getConnHandle(), 6, 12, 0, 200);
  }
  void onMTUChange(uint16_t mtu, NimBLEConnInfo &) override { peerMtu = mtu; }
  void onDisconnect(NimBLEServer *, NimBLEConnInfo &, int) override {
    subscribed = false; peerMtu = 23;
  }
};
class DataCallbacks : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic *, NimBLEConnInfo &info, uint16_t value) override {
    peerHandle = info.getConnHandle(); peerMtu = info.getMTU();
    subscribed = (value & 1) != 0;
  }
};
// Each notification consists of 10-byte little-endian records: u32 seq, u32 us, i16 raw.
// Separate queues ensure a blocked USB host never holds up BLE acquisition.
void sendBle(void *) {
  uint8_t packet[180];
  size_t count = 0;
  uint32_t oldest = 0;
  for (;;) {
    if (!subscribed.load() || webUpdating()) {
      xQueueReset(bleSamples); count = 0; vTaskDelay(pdMS_TO_TICKS(2)); continue;
    }
    const size_t capacity = std::min(size_t(18), size_t((peerMtu.load()-3)/10));
    Sample sample;
    if (count < capacity && xQueueReceive(bleSamples, &sample, pdMS_TO_TICKS(1)) == pdTRUE) {
      if (uint32_t(micros()-sample.us) > 100000) continue; // discard stale backlog, expose sequence gap
      if (!count) oldest = millis();
      uint8_t *p = packet + count*10;
      for (int i=0;i<4;++i) { p[i]=sample.seq>>(8*i); p[4+i]=sample.us>>(8*i); }
      p[8]=uint16_t(sample.raw); p[9]=uint16_t(sample.raw)>>8;
      ++count;
    }
    if (count && (count >= capacity || millis()-oldest >= 12)) {
      // A rejected notification is dropped, never retried out of order.
      bleData->notify(packet, count*10, peerHandle.load());
      count=0;
    }
  }
}

TaskHandle_t acquisition;
portMUX_TYPE irqLock = portMUX_INITIALIZER_UNLOCKED;
volatile uint32_t readySequence = 0, readyMicros = 0;

void ARDUINO_ISR_ATTR onReady() {
  BaseType_t wake = pdFALSE;
  portENTER_CRITICAL_ISR(&irqLock);
  readySequence = readySequence + 1;
  readyMicros = micros();
  portEXIT_CRITICAL_ISR(&irqLock);
  vTaskNotifyGiveFromISR(acquisition, &wake);
  if (wake) portYIELD_FROM_ISR();
}

void acquire(void *) {
  uint32_t lastSequence = 0;
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    if (webUpdating()) continue;
    Sample s;
    portENTER_CRITICAL(&irqLock);
    s.seq = readySequence; s.us = readyMicros;
    portEXIT_CRITICAL(&irqLock);
    if (s.seq == lastSequence) continue;
    lastSequence = s.seq;
    s.raw = ads.getLastConversionResults();
    portENTER_CRITICAL(&irqLock);
    const bool stable = (readySequence == s.seq);
    portEXIT_CRITICAL(&irqLock);
    // If a new conversion completed during I2C, discard this ambiguous pair.
    // Queue overflows and skipped conversions appear as sequence gaps on PC.
    if (stable) {
      webPublish(s.seq, s.us, s.raw);
      xQueueSend(samples, &s, 0);
      if (subscribed.load()) xQueueSend(bleSamples, &s, 0);
    }
  }
}

void initBle() {
  NimBLEDevice::init("ESP32-ECG");
  NimBLEDevice::setMTU(185);
  auto server = NimBLEDevice::createServer();
  bleServer = server;
  server->setCallbacks(new ServerCallbacks());
  server->advertiseOnDisconnect(true);
  auto service = server->createService(SERVICE_UUID);
  bleData = service->createCharacteristic(DATA_UUID, NIMBLE_PROPERTY::NOTIFY);
  bleData->setCallbacks(new DataCallbacks());
  bleStatus = service->createCharacteristic("c47e1002-17c4-4b56-9be5-125cece00001", NIMBLE_PROPERTY::READ);
  bleStatus->setValue("ECG2 starting; waiting for ADS1115");
  auto command = service->createCharacteristic(OTA_COMMAND_UUID, NIMBLE_PROPERTY::WRITE);
  command->setCallbacks(new OtaCallbacks());
  server->start();
  auto advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->enableScanResponse(true);
  advertising->setName("ESP32-ECG");
  advertising->start(); // loop retries if advertising did not start
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  webBoot(false);
  webBegin();
}

bool measurementStarted = false;
bool bluetoothStarted = false;
void startMeasurement() {
  measurementStarted = true;
  bootReason = uint32_t(esp_reset_reason());
  if (esp_reset_reason() != ESP_RST_SW) bleRecoveryRestarts = 0;
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  Wire.setTimeOut(20);
  samples = xQueueCreate(128, sizeof(Sample));
  bleSamples = xQueueCreate(128, sizeof(Sample));
  if (!samples || !bleSamples || xTaskCreate(acquire, "ecg_adc", 4096, nullptr, 3, &acquisition) != pdPASS) {
    for (;;) { serialTryLine("#ERROR allocation failed\n"); delay(1000); }
  }
  initBle(); bluetoothStarted = true;
  if (xTaskCreate(sendBle, "ecg_ble", 4096, nullptr, 1, nullptr) != pdPASS) {
    for (;;) { serialTryLine("#ERROR BLE task allocation failed\n"); delay(1000); }
  }
}

// Retry ADC startup without blocking BLE discovery or requiring a board reset.
void tryStartAdc() {
  static uint32_t lastAttempt = 0;
  if (adcStarted || millis() - lastAttempt < 1000) return;
  lastAttempt = millis();
  if (!ads.begin(ADC_ADDRESS, &Wire)) return;
  ads.setGain(GAIN_ONE);
  ads.setDataRate(RATE_ADS1115_860SPS);
  pinMode(RDY_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(RDY_PIN), onReady, FALLING);
  ads.startADCReading(DIFFERENTIAL ? ADS1X15_REG_CONFIG_MUX_DIFF_0_1
                                  : ADS1X15_REG_CONFIG_MUX_SINGLE_0, true);
  adcStarted = true;
  startupError = "ADC configured";
}

void loop() {
  webLoop();
  if (!measurementStarted) startMeasurement();
  if (otaRequested.exchange(false)) webArmOta();
  if (webUpdating()) { delay(1); return; }
  tryStartAdc();
  static uint32_t lastHealth = 0;
  if (bluetoothStarted && millis() - lastHealth >= 2000) {
    lastHealth = millis();
    auto advertising = NimBLEDevice::getAdvertising();
    recoverBle();
    uint32_t seq, stamp;
    portENTER_CRITICAL(&irqLock);
    seq = readySequence; stamp = readyMicros;
    portEXIT_CRITICAL(&irqLock);
    char status[180];
    snprintf(status, sizeof(status),
             "#ECG2 up=%lus reset=%lu adc=%s rdy=%lu age_ms=%lu ble=%u adv=%u\n",
             (unsigned long)(millis()/1000), (unsigned long)bootReason, startupError,
             (unsigned long)seq, (unsigned long)(uint32_t(micros()-stamp)/1000),
             unsigned(bleServer->getConnectedCount()), unsigned(advertising->isAdvertising()));
    String otaStatus = webOtaStatus();
    bleStatus->setValue(otaStatus.startsWith("OTA_") ? otaStatus.c_str() : status);
    // Show diagnostic heartbeat on serial only when ADC events are absent.
    if (!adcStarted || !seq || uint32_t(micros()-stamp) > 1000000) serialTryLine(status);
  }
  static Sample s;
  static bool pending = false;
  
  if (!pending) pending = xQueueReceive(samples, &s, 0) == pdTRUE;
  if (pending && uint32_t(micros()-s.us) > 100000) pending = false;
  if (pending) {
    char line[64];
    const int n = snprintf(line, sizeof(line), "E,%lu,%lu,%d\n",
                          (unsigned long)s.seq, (unsigned long)s.us, s.raw);
    if (Serial && Serial.availableForWrite() >= n) {
      Serial.write((const uint8_t *)line, n);
      pending = false;
    }
  }
  delay(1);
}
