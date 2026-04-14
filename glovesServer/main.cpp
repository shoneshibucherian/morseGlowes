//modified version capable of sending and receiving data to and from a Flask server using Socket.IO. It also displays the received data on an OLED screen and sends LoRa messages based on events from the Flask server.

#include "LoRaWan_APP.h"
#include "Arduino.h"
#include <Wire.h>
#include "HT_SSD1306Wire.h"
#include <WiFi.h>
#include <SocketIOclient.h>
#include <ArduinoJson.h>

// --- LoRa Settings ---
#define RF_FREQUENCY          915000000 // Hz
#define TX_OUTPUT_POWER       14        // dBm
#define LORA_BANDWIDTH        0         // 125 kHz
#define LORA_SPREADING_FACTOR 7         // SF7
#define LORA_CODINGRATE       1         // 4/5
#define BUFFER_SIZE           30
#define OLED_RST              21

char txpacket[BUFFER_SIZE];
char rxpacket[BUFFER_SIZE];
static RadioEvents_t RadioEvents;
bool lora_idle = true;
int16_t last_rssi = 0;
volatile bool rxFlag = false;

String lastReceived = "None";

static SSD1306Wire display(0x3c, 500000, SDA_OLED, SCL_OLED, GEOMETRY_128_64, RST_OLED);

const char* ssid = "SH1wifi";
const char* password = "hellome12";
const char* serverIP = "192.168.137.1";
const int port = 5000;

SocketIOclient socketIO;
bool wsConnected = false;

void displayMessage(String line1, String line2 = "") {
    display.clear();
    display.setFont(ArialMT_Plain_10);
    display.setTextAlignment(TEXT_ALIGN_CENTER);
    display.drawString(64, 20, line1);
    if (line2 != "") {
        display.drawString(64, 35, line2);
    }
    display.display();
}

// --- LoRa Callbacks ---
void OnTxDone(void) {
    Serial.println("TX Done. Returning to Listen mode...");
    lora_idle = true;
    Radio.Rx(0); 
}

void OnTxTimeout(void) { 
    Radio.Sleep(); 
    lora_idle = true; 
}

void OnRxDone(uint8_t *payload, uint16_t size, int16_t rssi, int8_t snr) {
    last_rssi = rssi;
    memcpy(rxpacket, payload, size);
    rxpacket[size] = '\0';
    lastReceived = rxpacket;
    lora_idle = true;
    rxFlag = true;
    Serial.printf("Received LoRa: %s\n", lastReceived.c_str());
}

void socketIOEvent(socketIOmessageType_t type, uint8_t* payload, size_t length) {
    switch(type) {
        case sIOtype_CONNECT:
            Serial.println("Socket.IO Connected!");
            wsConnected = true;
            socketIO.send(sIOtype_CONNECT, "/");
            displayMessage("Connected!", "to Flask");
            break;

        case sIOtype_DISCONNECT:
            Serial.println("Socket.IO Disconnected!");
            wsConnected = false;
            displayMessage("Disconnected", "Reconnecting...");
            break;

        case sIOtype_EVENT: {
            String msg = String((char*)payload);
            JsonDocument doc;
            deserializeJson(doc, msg);
            
            // Check both possible JSON paths
            String content = doc[1]["message"].as<String>(); 
            if (content == "null") content = doc["message"].as<String>();

            if (content != "null" && content.length() > 0) {
                displayMessage("Sending...", content);
                
                // FORCE the radio to stop whatever it's doing
                Radio.Standby(); 
                lora_idle = false; 
                
                Serial.println("LoRa TX Start: " + content);
                sprintf(txpacket, "%s", content.c_str());
                Radio.Send((uint8_t *)txpacket, strlen(txpacket));
                Serial.println("reached");
            }
            break;
        }
        case sIOtype_ERROR:
            Serial.print("SocketIO Error Payload: ");
            if (payload) Serial.println((char*)payload);
            break;
            
        default:
            break;
    }
}

void setup() {
    Serial.begin(115200);
    Mcu.begin(HELTEC_BOARD, SLOW_CLK_TPYE);
    
    pinMode(Vext, OUTPUT);
    digitalWrite(Vext, LOW);
    delay(100);
    
    pinMode(OLED_RST, OUTPUT);
    digitalWrite(OLED_RST, LOW);
    delay(50);
    digitalWrite(OLED_RST, HIGH);
    delay(50);

    RadioEvents.TxDone = OnTxDone;
    RadioEvents.TxTimeout = OnTxTimeout;
    RadioEvents.RxDone = OnRxDone;
    
    Radio.Init(&RadioEvents);
    Radio.SetChannel(RF_FREQUENCY);
    Radio.SetTxConfig(MODEM_LORA, TX_OUTPUT_POWER, 0, LORA_BANDWIDTH, LORA_SPREADING_FACTOR, LORA_CODINGRATE, 8, false, true, 0, 0, false, 3000);
    Radio.SetRxConfig(MODEM_LORA, LORA_BANDWIDTH, LORA_SPREADING_FACTOR, LORA_CODINGRATE, 0, 8, 0, false, 0, true, 0, 0, false, true);

    display.init();
    display.flipScreenVertically();
    displayMessage("Hello!");
    delay(2000);

    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);

    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nConnected!");
    displayMessage("WiFi Connected", WiFi.localIP().toString());

    socketIO.begin(serverIP, port, "/socket.io/?EIO=4");
    socketIO.onEvent(socketIOEvent);
}

void loop() {
    Radio.IrqProcess();
    socketIO.loop();
    
    if (WiFi.status() != WL_CONNECTED) {
        WiFi.disconnect();
        WiFi.begin(ssid, password);
        delay(500);
    }

    if (rxFlag) {
        rxFlag = false;
        if (wsConnected) {
            String payload = "[\"lora_data\",{\"message\":\"" + lastReceived + "\"}]";
            socketIO.sendEVENT(payload);
            Serial.println("Sent to Flask: " + payload);
        }
        Radio.Rx(0); 
    }
    
    if (lora_idle) {
        Radio.Rx(0);
        lora_idle = false;
    }
    
    yield();
}