#include <WiFi.h>
#include <time.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

const char* ssid     = "timberlawn-kids";
const char* password = "11005Sugarbush";
const char* ntpServer = "pool.ntp.org";
const long  gmtOffset_sec = -18000;
const int   daylightOffset_sec = 3600;

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C
#define SDA_PIN 8
#define SCL_PIN 9

Adafruit_SH1106G display = Adafruit_SH1106G(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

const int pinCLK = 10;
const int pinDT = 2;
const int pinSW = 3;

volatile int volumeChange = 0; 
int pcVolume = 0;
unsigned long lastTickMillis = 0;
unsigned long volDisplayTimeout = 0; 
int currentPos = 0, totalDur = 0;
bool isPlaying = false, pcConnected = false;
String currentSong = "", lastSong = "";
String currentCPU = "0", currentRAM = "0", currentH = "12", currentM = "00";
int visualizerBars[12] = {0};

unsigned long lastButtonPress = 0;
int clickCount = 0;
const int clickTimeout = 400;

void IRAM_ATTR readEncoder() {
  static int lastCLK = -1;
  int currentCLK = digitalRead(pinCLK);
  if (currentCLK != lastCLK && currentCLK == LOW) {
    if (digitalRead(pinDT) == currentCLK) { volumeChange++; } 
    else { volumeChange--; }
  }
  lastCLK = currentCLK;
}

String formatTime(int totalSeconds) {
  int minutes = totalSeconds / 60;
  int seconds = totalSeconds % 60;
  return String(minutes) + ":" + (seconds < 10 ? "0" : "") + String(seconds);
}

void drawCenteredText(String text, int y, int size) {
  display.setTextSize(size);
  int16_t x1, y1; uint16_t w, h;
  display.getTextBounds(text, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((SCREEN_WIDTH - w) / 2, y);
  display.print(text);
}

String getValue(String data, char separator, int index) {
  int found = 0, strIndex[] = {0, -1}, maxIndex = data.length() - 1;
  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == separator || i == maxIndex) {
      found++;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}

bool barsAllZero() {
  for (int i = 0; i < 12; i++) { if (visualizerBars[i] > 0) return false; }
  return true;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  pinMode(pinCLK, INPUT_PULLUP);
  pinMode(pinDT, INPUT_PULLUP);
  pinMode(pinSW, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(pinCLK), readEncoder, CHANGE);
  if (!display.begin(SCREEN_ADDRESS, true)) { for (;;); }
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  drawCenteredText("Connecting WiFi...", 25, 1);
  display.display();
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); }
  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
}

void loop() {
  if (volumeChange != 0) {
    volDisplayTimeout = millis(); 
    if (volumeChange > 0) { for(int i=0; i<abs(volumeChange); i++) Serial.println("CW"); } 
    else { for(int i=0; i<abs(volumeChange); i++) Serial.println("CCW"); }
    volumeChange = 0;
  }

  bool btnState = (digitalRead(pinSW) == LOW);
  static bool lastBtnState = false;
  if (btnState && !lastBtnState) { clickCount++; lastButtonPress = millis(); }
  lastBtnState = btnState;
  if (clickCount > 0 && (millis() - lastButtonPress > clickTimeout)) {
    if (clickCount == 1) Serial.println("PAUSE");
    else if (clickCount == 2) Serial.println("NEXT");
    else if (clickCount == 3) Serial.println("PREV");
    clickCount = 0;
  }

  if (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    if (data.indexOf('|') != -1) { 
      pcConnected = true;
      currentCPU  = getValue(data, '|', 0);
      currentRAM  = getValue(data, '|', 1);
      currentSong = getValue(data, '|', 2);
      int incomingPos = getValue(data, '|', 3).toInt();
      totalDur    = getValue(data, '|', 4).toInt();
      String barsString = getValue(data, '|', 5);
      currentH    = getValue(data, '|', 6);
      currentM    = getValue(data, '|', 7);
      isPlaying   = (getValue(data, '|', 8).toInt() == 1);
      pcVolume    = getValue(data, '|', 9).toInt();

      if (currentSong != lastSong || abs(incomingPos - currentPos) > 5) { 
        currentPos = incomingPos; 
        lastSong = currentSong; 
      }
      for (int i = 0; i < 12; i++) {
        visualizerBars[i] = getValue(barsString, ',', i).toInt();
      }
    }
  }

  if (isPlaying && (millis() - lastTickMillis >= 1000)) {
    lastTickMillis = millis();
    if (currentPos < totalDur) currentPos++;
  }

  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  struct tm timeinfo;
  bool timeValid = getLocalTime(&timeinfo);

  if (millis() - volDisplayTimeout < 1500) {
    drawCenteredText("VOLUME", 10, 1);
    drawCenteredText(String(pcVolume) + "%", 25, 3);
    display.drawRect(10, 52, 108, 8, SH110X_WHITE);
    int volBar = map(pcVolume, 0, 100, 0, 104);
    display.fillRect(12, 54, volBar, 4, SH110X_WHITE);
  } 
  else if (!pcConnected) {
    if (timeValid) {
      char hStr[5], mStr[5], dStr[30];
      strftime(hStr, 5, "%I", &timeinfo); strftime(mStr, 5, "%M", &timeinfo);
      strftime(dStr, 30, "%b %d", &timeinfo);
      String finalH = String(hStr); if(finalH.startsWith("0")) finalH = finalH.substring(1);
      drawCenteredText(finalH + ":" + String(mStr), 15, 3);
      drawCenteredText(String(dStr), 50, 1);
    }
  } else {
    String topStr = "C:" + currentCPU + "% R:" + currentRAM;
    drawCenteredText(topStr, 6, 1);
    display.drawLine(0, 15, 128, 15, SH110X_WHITE);

    if (isPlaying || !barsAllZero()) {
      display.setCursor(0, 20); display.print(currentSong.substring(0, 20)); 
      display.setCursor(0, 32); display.print(formatTime(currentPos) + " / " + formatTime(totalDur));
      display.drawRect(0, 42, 128, 5, SH110X_WHITE);
      if (totalDur > 0) {
        int barWidth = map(constrain(currentPos, 0, totalDur), 0, totalDur, 0, 126);
        display.fillRect(1, 43, barWidth, 3, SH110X_WHITE);
      }
      for (int i = 0; i < 12; i++) {
        int barH = map(visualizerBars[i], 0, 32, 0, 16); 
        display.fillRect(i * 10 + 4, 64 - barH, 7, barH, SH110X_WHITE);
      }
    } else {
      drawCenteredText(currentH + ":" + currentM, 30, 3);
    }
  }
  display.display();
}
