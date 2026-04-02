#include <Arduino.h>
#include <WiFi.h>
#include <SocketIOclient.h>
#include <ArduinoJson.h>
#include <SSD1306Wire.h>
#define OLED_RST 21

SSD1306Wire display(0x3c, 17, 18);

const char* ssid = "WiFi SSID";
const char* password = "WiFi Password";
const char* serverIP = "WiFi DHCP IP Address";
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

void socketIOEvent(socketIOmessageType_t type, uint8_t* payload, size_t length) {
    switch(type) {
        case sIOtype_DISCONNECT:
            Serial.println("Socket.IO Disconnected!");
            wsConnected = false;
            displayMessage("Disconnected", "Reconnecting...");
            break;
        case sIOtype_CONNECT:
            Serial.println("Socket.IO Connected!");
            wsConnected = true;
            socketIO.send(sIOtype_CONNECT, "/");
            displayMessage("Connected!", "to Flask");
            break;
        case sIOtype_EVENT: {
            String msg = String((char*)payload);
            Serial.println("Received from Flask: " + msg);
            JsonDocument doc;
            deserializeJson(doc, msg);
            String content = doc[1]["message"].as<String>();
            displayMessage("Flask says:", content);
            break;
        }
        case sIOtype_ERROR:
            Serial.println("Socket.IO Error!");
            displayMessage("Error!", "Check connection");
            break;
    }
}

void setup() {
    Serial.begin(115200);
    
    // Enable Vext power to OLED
    pinMode(Vext, OUTPUT);
    digitalWrite(Vext, LOW);
    delay(100);
    
    // Reset OLED
    pinMode(OLED_RST, OUTPUT);
    digitalWrite(OLED_RST, LOW);
    delay(50);
    digitalWrite(OLED_RST, HIGH);
    delay(50);
    
    display.init();
    display.flipScreenVertically();
    display.clear();
    display.setFont(ArialMT_Plain_10);
    display.setTextAlignment(TEXT_ALIGN_LEFT);
    display.drawString(0, 0, "Hello!");
    display.display();
    delay(3000);
    display.clear();
    display.setFont(ArialMT_Plain_10);
    display.setTextAlignment(TEXT_ALIGN_CENTER);
    display.drawString(64, 20, "Connecting to");
    display.drawString(64, 35, "WiFi...");
    display.display();

    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);

    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nConnected! IP: " + WiFi.localIP().toString());
    displayMessage("WiFi Connected!", WiFi.localIP().toString());
    delay(2000);

    socketIO.begin(serverIP, port, "/socket.io/?EIO=4");
    socketIO.onEvent(socketIOEvent);
}

void loop() {
    socketIO.loop();

    // Test code - real Morse input will come from capacitive touch
    /*if (wsConnected) {
         static unsigned long lastSend = 0;
         if (millis() - lastSend > 5000) {
             String payload = "[\"esp32_message\",{\"morse\":\".... . .-.. .-.. ---\",\"device_id\":\"esp32_glove\"}]";
             socketIO.sendEVENT(payload);
             Serial.println("Sent to Flask: " + payload);
             lastSend = millis();
        }
    }*/
}