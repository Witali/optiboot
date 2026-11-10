// GPL-2.0-or-later. USB/UART smoke test for the tested ATmega328PB Nano.
#include <Arduino.h>

#if !defined(__AVR_ATmega328PB__)
#error Select MiniCore ATmega328 with variant 328PB.
#endif
#if F_CPU != 16000000UL
#error Select External 16 MHz.
#endif

static unsigned long lastBlink;
static unsigned long lastReport;
static unsigned long counter;
static bool ledOn;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.begin(115200);
  Serial.println(F("SMOKE_READY ATmega328PB 16MHz UART0 115200"));
}

void loop() {
  const unsigned long now = millis();
  if (now - lastBlink >= 500UL) {
    lastBlink = now;
    ledOn = !ledOn;
    digitalWrite(LED_BUILTIN, ledOn ? HIGH : LOW);
  }
  while (Serial.available() > 0) {
    Serial.write(Serial.read());
  }
  if (now - lastReport >= 1000UL) {
    lastReport = now;
    Serial.print(F("counter="));
    Serial.println(++counter);
  }
}
