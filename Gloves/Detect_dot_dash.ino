
#include "Arduino.h"

// Pin Definitions
const int dot_pin   = 7;
const int dash_pin  = 6;
const int space_pin = 5;
const int sent_pin  = 4;

uint32_t dot_threshold = 500000;
uint32_t dash_threshold = 283000;
uint32_t space_threshold = 500000;
uint32_t sent_threshold = 500000;

void setup() {
  Serial.begin(115200);
  while(!Serial); 
  
  touchSetCycles(0x2000, 0x100); 

  // Calibration: Read a pin and set threshold to 90% of the baseline

}

void loop() {
  uint32_t v_dot   = touchRead(dot_pin);
  uint32_t v_dash  = touchRead(dash_pin);
  uint32_t v_space = touchRead(space_pin);
  uint32_t v_sent  = touchRead(sent_pin);

  // Check for DROPS below threshold
  if (v_dot > dot_threshold) {
    Serial.print("DOT detected");
    Serial.println(v_dot);
    delay(200); // Simple debounce
  }
  
  if (v_dash >= dash_threshold) {
    Serial.print("DASH detected");
    Serial.println(v_dash);
    delay(400);
  }
  
  if (v_space >= space_threshold) {
    Serial.print("SPACE detected");
    Serial.println(v_space);
    delay(300);
  }
  
  if (v_sent > sent_threshold) {
    Serial.print("SENT detected");
    Serial.println(v_sent);
    delay(200);
  }

  delay(50); // Faster polling for better responsiveness
}
