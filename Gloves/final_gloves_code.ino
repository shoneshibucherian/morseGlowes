#include "LoRaWan_APP.h"
#include "Arduino.h"
#include <Wire.h>
#include "HT_SSD1306Wire.h"

// --- Hardware Pins & Thresholds ---
const int PIN_DOT = 7, PIN_DASH = 6, PIN_SPACE = 5, PIN_DEL = 4, PIN_SENT = 3;
const uint32_t threshold = 600000;

// --- LoRa Settings ---
#define RF_FREQUENCY                915000000 // Hz
#define TX_OUTPUT_POWER             14        // dBm
#define LORA_BANDWIDTH              0         // 125 kHz
#define LORA_SPREADING_FACTOR       7         // SF7
#define LORA_CODINGRATE             1         // 4/5
#define BUFFER_SIZE                 30

char txpacket[BUFFER_SIZE];
char rxpacket[BUFFER_SIZE];
static RadioEvents_t RadioEvents;
bool lora_idle = true;
int16_t last_rssi = 0;
volatile bool rxFlag = false;

// --- OLED Setup ---
static SSD1306Wire display(0x3c, 500000, SDA_OLED, SCL_OLED, GEOMETRY_128_64, RST_OLED);

// --- Morse Table ---
struct MorseChar { char c; const char* code; };
const MorseChar morseTable[] = {
    {'A', ".-"}, {'B', "-..."}, {'C', "-.-."}, {'D', "-.."}, {'E', "."},
    {'F', "..-."}, {'G', "--."}, {'H', "...."}, {'I', ".."}, {'J', ".---"},
    {'K', "-.-"}, {'L', ".-.."}, {'M', "--"}, {'N', "-."}, {'O', "---"},
    {'P', ".--."}, {'Q', "--.-"}, {'R', ".-."}, {'S', "..."}, {'T', "-"},
    {'U', "..-"}, {'V', "...-"}, {'W', ".--"}, {'X', "-..-"}, {'Y', "-.--"}, {'Z', "--.."}
};
const int tableSize = sizeof(morseTable) / sizeof(MorseChar);

// --- State Variables ---
String currentCode = "";
String message = "";
String lastReceived = "None";
bool isPressed[5] = {false, false, false, false, false};

void VextON() { pinMode(Vext, OUTPUT); digitalWrite(Vext, LOW); }

// --- LoRa Callbacks ---
void OnTxDone(void) { Serial.println("TX Done"); lora_idle = true; }
void OnTxTimeout(void) { Radio.Sleep(); lora_idle = true; }
void OnRxDone(uint8_t *payload, uint16_t size, int16_t rssi, int8_t snr) {
    last_rssi = rssi;
    memcpy(rxpacket, payload, size);
    rxpacket[size] = '\0';
    lastReceived = rxpacket;
    Radio.Sleep();
    lora_idle = true;
    rxFlag = true;
    Serial.printf("Received: %s\n", lastReceived);
}

void updateScreen() {
    display.clear();
    display.setFont(ArialMT_Plain_10);
    
    // 1. Outgoing Message
    display.drawString(0, 0, "OUT: " + message + "_");
    display.drawString(0, 11, "CODE: " + currentCode);
    display.drawLine(0, 23, 128, 23);

    // 2. Incoming Message
    display.drawString(0, 24, "IN: " + lastReceived);
    // if(last_rssi != 0) display.drawString(85, 24, String(last_rssi));
    display.drawLine(0, 36, 128, 36);
    
    // 3. Filtered Keyboard
    int x = 2, y = 38, spacing = 9;
    for (int i = 0; i < tableSize; i++) {
        String code = String(morseTable[i].code);
        if (code.startsWith(currentCode)) {
            display.drawString(x, y + 2, String(morseTable[i].c));
            if (code.length() > currentCode.length()) {
                char next = code[currentCode.length()];
                if (next == '.') display.fillRect(x + 3, y, 2, 2);
                if (next == '-') display.fillRect(x + 1, y, 6, 1);
            }
            x += spacing;
            if (x > 120) { x = 2; y += 14; }
        }
    }
    display.display();
}

void setup() {
    Serial.begin(115200);
    VextON(); delay(100);
    Mcu.begin(HELTEC_BOARD, SLOW_CLK_TPYE);

    // LoRa Init
    RadioEvents.TxDone = OnTxDone;
    RadioEvents.TxTimeout = OnTxTimeout;
    RadioEvents.RxDone = OnRxDone;
    Radio.Init(&RadioEvents);
    Radio.SetChannel(RF_FREQUENCY);
    Radio.SetTxConfig(MODEM_LORA, TX_OUTPUT_POWER, 0, LORA_BANDWIDTH, LORA_SPREADING_FACTOR, LORA_CODINGRATE, 8, false, true, 0, 0, false, 3000);
    Radio.SetRxConfig(MODEM_LORA, LORA_BANDWIDTH, LORA_SPREADING_FACTOR, LORA_CODINGRATE, 0, 8, 0, false, 0, true, 0, 0, false, true);

    display.init();
    display.setContrast(255);
    touchSetCycles(0x2000, 0x100);
    updateScreen();
}

void loop() {
    bool changed = false;
    uint32_t v[] = {touchRead(PIN_DOT), touchRead(PIN_DASH), touchRead(PIN_SPACE), touchRead(PIN_DEL), touchRead(PIN_SENT)};

    // --- Input Handling ---
    if (v[0] > threshold && !isPressed[0]) { currentCode += "."; changed = true; isPressed[0] = true; } 
    else if (v[0] < threshold) isPressed[0] = false;

    if (v[1] > threshold && !isPressed[1]) { currentCode += "-"; changed = true; isPressed[1] = true; }
    else if (v[1] < threshold) isPressed[1] = false;

    if (v[2] > threshold && !isPressed[2]) {
        for (int j = 0; j < tableSize; j++) {
            if (currentCode == String(morseTable[j].code)) { message += morseTable[j].c; break; }
        }
        currentCode = ""; changed = true; isPressed[2] = true;
    } 
    else if (v[2] < threshold) isPressed[2] = false;

    if (v[3] > threshold && !isPressed[3]) {
        Serial.print("SENT detected");
        Serial.print(v[3]);
        if (currentCode.length() > 0) currentCode.remove(currentCode.length() - 1);
        else if (message.length() > 0) message.remove(message.length() - 1);
        changed = true; isPressed[3] = true;
    }
    else if (v[3] < threshold) isPressed[3] = false;
    
    // --- Send Logic ---
    if (v[4] > threshold && !isPressed[4]  && message.length() > 0) {
        isPressed[4] = true;
        Serial.print("SENT detected");
        Serial.println(v[4]);
        sprintf(txpacket, "%s", message.c_str());
        Radio.Send((uint8_t *)txpacket, strlen(txpacket));
        lora_idle = false;
        message = ""; 
        changed = true;
    }
    else if (v[4] < threshold) isPressed[4] = false;

    // --- RX/TX State Management ---
    if (lora_idle) {
        lora_idle = false;
        Radio.Rx(0); // Go back to listening
    }

    if (changed) updateScreen();

    if (rxFlag) {
        updateScreen();
        rxFlag = false;
    }
    Radio.IrqProcess();
    delay(10);
}
