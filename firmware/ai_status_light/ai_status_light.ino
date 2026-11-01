#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <esp_system.h>

// Onboard RGB LED; the build script selects GPIO48 or GPIO38.
#ifndef CAR_LED_PIN
#define CAR_LED_PIN 48
#endif
#ifndef CAR_LED_COUNT
#define CAR_LED_COUNT 1
#endif
#ifndef CAR_BRIGHTNESS
#define CAR_BRIGHTNESS 32
#endif
constexpr uint8_t LED_PIN = CAR_LED_PIN;
constexpr uint16_t LED_COUNT = CAR_LED_COUNT;
constexpr uint8_t USER_BOOT_GPIO = 0;
constexpr uint8_t BRIGHTNESS = CAR_BRIGHTNESS;
constexpr uint32_t LINK_TIMEOUT_MS = 3500;
Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

enum class Status { Disconnected, Unknown, Idle, Running, Paused, Waiting, Pending, Error };
Status state = Status::Disconnected;
uint32_t lastHost = 0, bootId = 0, buttonSeq = 0;
bool linked = false;
char line[96];
size_t lineLength = 0;
bool overflow = false;

void ready() {
  Serial.printf("CAR1 READY %08lx\n", (unsigned long)bootId);
  Serial.printf("CAR1 INFO led_pin=%u led_count=%u\n", LED_PIN, LED_COUNT);
}

bool parseStatus(const char* s, Status& value) {
  const char* names[] = {"disconnected", "unknown", "idle", "running", "paused", "waiting", "pending", "error"};
  for (uint8_t i = 0; i < 8; ++i) {
    if (strcmp(s, names[i]) == 0) { value = static_cast<Status>(i); return true; }
  }
  return false;
}

void receive() {
  // Limit work per loop so serial noise cannot starve the button or watchdog.
  for (int budget = 0; budget < 256 && Serial.available(); ++budget) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c == '\n') {
      line[lineLength] = '\0';
      if (!overflow) {
        if (strcmp(line, "CAR1 HELLO") == 0) ready();
        else if (strncmp(line, "CAR1 STATE ", 11) == 0) {
          Status parsed;
          if (parseStatus(line + 11, parsed)) {
            state = parsed;
            lastHost = millis();
            linked = true;
            Serial.printf("CAR1 ACK %s\n", line + 11);
          }
        }
      }
      lineLength = 0;
      overflow = false;
    } else if (!overflow && lineLength < sizeof(line) - 1) line[lineLength++] = c;
    else overflow = true;
  }
}

void readButton(uint32_t now) {
  static bool lastRaw = HIGH, stable = HIGH, armed = false;
  static uint32_t changed = 0, pressedAt = 0;
  const bool raw = digitalRead(USER_BOOT_GPIO);
  if (raw != lastRaw) { lastRaw = raw; changed = now; }
  if (uint32_t(now - changed) < 40) return;
  if (raw == HIGH && stable == HIGH) armed = true; // Ignore held BOOT at startup.
  if (raw == stable) return;
  stable = raw;
  if (stable == LOW) pressedAt = now;
  else {
    const uint32_t duration = now - pressedAt;
    if (armed && linked && now - lastHost <= LINK_TIMEOUT_MS && duration >= 50 && duration <= 1200) {
      Serial.printf("CAR1 BUTTON %08lx %lu\n", (unsigned long)bootId, (unsigned long)++buttonSeq);
    }
    armed = true;
  }
}

void draw(uint32_t now) {
  static uint32_t lastDraw = 0;
  if (now - lastDraw < 30) return;
  lastDraw = now;
  const Status shown = linked && now - lastHost <= LINK_TIMEOUT_MS ? state : Status::Disconnected;
  uint8_t r = 0, g = 0, b = 0;
  const bool blink = (now / 400) % 2 == 0;
  switch (shown) {
    case Status::Running: g = 255; break;
    case Status::Paused: r = 255; g = 120; break;
    case Status::Idle: b = 100; break;
    case Status::Waiting: if (blink) { r = 255; g = 120; } break;
    case Status::Pending: if ((now / 150) % 2 == 0) { r = 80; g = 80; b = 80; } break;
    case Status::Error: if (blink) r = 255; break;
    case Status::Unknown: if (blink) { r = 160; b = 160; } break;
    case Status::Disconnected: if ((now / 800) % 2 == 0) b = 180; break;
  }
  pixels.fill(pixels.Color(r, g, b));
  pixels.show();
}

void setup() {
  pinMode(USER_BOOT_GPIO, INPUT_PULLUP);
  pixels.begin();
  pixels.setBrightness(BRIGHTNESS);
  pixels.clear();
  pixels.show();
  // Board's USB-to-UART connector, not the native USB/OTG connector.
  Serial.begin(115200);
  bootId = esp_random();
  ready();
}

void loop() {
  receive();
  const uint32_t now = millis();
  readButton(now);
  draw(now);
  delay(1);
}
