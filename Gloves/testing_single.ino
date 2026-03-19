#include "Arduino.h"

const int pins[] = {7, 6, 5, 4, 3};
const char* names[] = {"DOT", "DASH", "SPACE", "SENT", "RESET"};

void setup() {
  Serial.begin(115200);
  delay(2000);
  // The S3 needs a slightly longer sample time to be stable
  touchSetCycles(0x2000, 0x100); 
  Serial.println("--- TOUCH DEBUG START ---");
}

void loop() {
  for (int i = 0; i < 5; i++) {
    uint32_t val = touchRead(pins[i]);
    Serial.print(names[i]);
    Serial.print(": ");
    Serial.print(val);
    Serial.print("  |  ");
  }
  Serial.println(); // New line for each scan
  delay(300);
}
