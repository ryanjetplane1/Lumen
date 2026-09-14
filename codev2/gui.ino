#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <math.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C
#define SDA_PIN 8
#define SCL_PIN 9

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

float totalDur = 0.0f;
float basePos = 0.0f;
unsigned long basePosTime = 0;
float lastIncomingPos = 0.0f;
bool haveIncomingPos = false;
bool isPlaying = false, pcConnected = false;
bool everReceivedSerial = false;
unsigned long lastPcDataTime = 0;
String currentSong = "", lastSong = "";
String currentCPU = "0", currentRAM = "0", currentH = "12", currentM = "00";
String currentArtist = "";

bool lastIsPlayingState = false;
unsigned long playStartTime = 0;
const unsigned long BARS_RAMP_MS = 1000;
int visualizerBars[12] = {0};
float displayBars[12] = {0};
unsigned long lastBarsUpdateTime = 0;
const float BAR_FALL = 1.6;
const unsigned long BARS_STALE_MS = 600;

String serialBuffer = "";

int  scrollOffset    = 0;
unsigned long lastScrollTime  = 0;
const int SCROLL_SPEED_MS     = 350;
const int SCROLL_PAUSE_MS     = 2000;
const int MAX_VISIBLE_CHARS   = 21;
bool scrollPausing            = false;
unsigned long scrollPauseStart = 0;
String lastScrollSong         = "";

unsigned long lastDisplayUpdate = 0;
const int DISPLAY_UPDATE_MS     = 50;

bool lastPcConnected      = false;
bool displayPcConnected   = false;
unsigned long pcChangeTime = 0;
const unsigned long PC_DEBOUNCE_MS = 1500;
const unsigned long PC_TIMEOUT_MS  = 2000;

String formatTime(int totalSeconds) {
  int m = totalSeconds / 60, s = totalSeconds % 60;
  return String(m) + ":" + (s < 10 ? "0" : "") + String(s);
}

void drawCenteredText(String text, int y, int size) {
  display.setTextSize(size);
  int16_t x1, y1; uint16_t w, h;
  display.getTextBounds(text, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((SCREEN_WIDTH - w) / 2, y);
  display.print(text);
}

String getValue(String data, char sep, int index) {
  int found = 0, strIndex[] = {0, -1}, maxIndex = data.length() - 1;
  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == sep || i == maxIndex) {
      found++;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}

String oledText(String text) {
  String clean;
  clean.reserve(text.length());
  for (unsigned int i = 0; i < text.length(); i++) {
    char c = text.charAt(i);
    clean += (c >= 32 && c <= 126) ? c : '?';
  }
  return clean;
}

bool barsAllZero() {
  for (int i = 0; i < 12; i++) if (visualizerBars[i] > 0) return false;
  return true;
}

void processSerialLine(String data) {
  if (data.indexOf('|') == -1) return;
  unsigned long now = millis();
  pcConnected  = true;
  everReceivedSerial = true;
  lastPcDataTime = millis();
  currentCPU   = getValue(data, '|', 0);
  currentRAM   = getValue(data, '|', 1);
  String incomingSong = oledText(getValue(data, '|', 2));
  float incomingPos = getValue(data, '|', 3).toFloat();
  float incomingDur = getValue(data, '|', 4).toFloat();
  String barsString = getValue(data, '|', 5);
  currentH     = getValue(data, '|', 6);
  currentM     = getValue(data, '|', 7);
  bool incomingPlaying = (getValue(data, '|', 8).toInt() == 1);
  String incomingArtist = oledText(getValue(data, '|', 9));

  bool trackChanged = incomingSong != currentSong ||
                      incomingArtist != currentArtist ||
                      incomingDur != totalDur;
  bool playStateChanged = incomingPlaying != isPlaying;
  float localPos = basePos;
  if (isPlaying) {
    localPos += (now - basePosTime) / 1000.0f;
  }
  bool positionJumped = haveIncomingPos &&
                        fabsf(incomingPos - lastIncomingPos) > 3.0f;

  if (trackChanged || positionJumped || (playStateChanged && incomingPlaying)) {
    basePos = incomingPos;
    basePosTime = now;
  } else if (playStateChanged) {
    basePos = max(localPos, incomingPos);
    basePosTime = now;
  }
  lastIncomingPos = incomingPos;
  haveIncomingPos = true;

  currentSong  = incomingSong;
  totalDur     = incomingDur;
  isPlaying    = incomingPlaying;
  currentArtist = incomingArtist;
  lastSong     = currentSong;
  for (int i = 0; i < 12; i++)
    visualizerBars[i] = getValue(barsString, ',', i).toInt();
  lastBarsUpdateTime = millis();
}

void pollSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      processSerialLine(serialBuffer);
      serialBuffer = "";
    } else if (c != '\r') {
      serialBuffer += c;
      if (serialBuffer.length() > 200) serialBuffer = "";
    }
  }
}

void drawScrollingSong(String song, int y) {
  display.setTextSize(1);
  if (song != lastScrollSong) {
    scrollOffset     = 0;
    scrollPausing    = true;
    scrollPauseStart = millis();
    lastScrollSong   = song;
  }
  int songLen = song.length();
  if (songLen <= MAX_VISIBLE_CHARS) {
    display.setCursor(0, y);
    display.print(song);
    return;
  }
  if (scrollPausing) {
    if (millis() - scrollPauseStart >= SCROLL_PAUSE_MS) {
      scrollPausing  = false;
      lastScrollTime = millis();
    }
    display.setCursor(0, y);
    display.print(song.substring(0, MAX_VISIBLE_CHARS));
    return;
  }
  if (millis() - lastScrollTime >= SCROLL_SPEED_MS) {
    scrollOffset++;
    lastScrollTime = millis();
    if (scrollOffset >= songLen + 3) {
      scrollOffset     = 0;
      scrollPausing    = true;
      scrollPauseStart = millis();
    }
  }
  String padded = song + "   " + song;
  display.setCursor(0, y);
  display.print(padded.substring(scrollOffset, scrollOffset + MAX_VISIBLE_CHARS));
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) { for (;;); }
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  drawCenteredText("Waiting for PC...", 25, 1);
  display.display();
  serialBuffer.reserve(200);
}

void loop() {
  pollSerial();

  if (isPlaying && !lastIsPlayingState) {
    playStartTime = millis();
    for (int i = 0; i < 12; i++) displayBars[i] = 0;
  }
  lastIsPlayingState = isPlaying;

  if (millis() - lastDisplayUpdate < DISPLAY_UPDATE_MS) return;
  lastDisplayUpdate = millis();

  float shownPos = basePos;
  if (isPlaying) {
    shownPos = basePos + (millis() - basePosTime) / 1000.0f;
    if (totalDur > 0 && shownPos > totalDur) shownPos = totalDur;
  }

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  bool pcNow = everReceivedSerial && (millis() - lastPcDataTime < PC_TIMEOUT_MS);
  if (pcNow != lastPcConnected) {
    lastPcConnected = pcNow;
    pcChangeTime    = millis();
  }
  if (millis() - pcChangeTime >= PC_DEBOUNCE_MS) {
    displayPcConnected = pcNow;
  }

  if (!displayPcConnected) {
    drawCenteredText("Waiting for PC...", 25, 1);
  } else {
    drawCenteredText("C:" + currentCPU + "% R:" + currentRAM, 2, 1);
    display.drawLine(0, 11, 128, 11, SSD1306_WHITE);

    if (isPlaying || !barsAllZero()) {
      String scrollText = currentArtist.length() > 0 ? currentSong + " - " + currentArtist : currentSong;
      drawScrollingSong(scrollText, 20);
      display.setCursor(0, 32);
      display.print(formatTime((int)(shownPos + 0.5f)) + " / " + formatTime((int)(totalDur + 0.5f)));
      display.drawRect(0, 42, 128, 5, SSD1306_WHITE);
      if (totalDur > 0) {
        int barWidth = (int)(constrain(shownPos, 0.0f, totalDur) / totalDur * 126.0f);
        display.fillRect(1, 43, barWidth, 3, SSD1306_WHITE);
      }
      bool barsStale = (millis() - lastBarsUpdateTime > BARS_STALE_MS);
      unsigned long playElapsed = millis() - playStartTime;
      float rampFactor = constrain(playElapsed / (float)BARS_RAMP_MS, 0.0f, 1.0f);
      float endFactor = 1.0f;
      if (totalDur > 0.0f && totalDur - shownPos < 2.0f) {
        endFactor = constrain((totalDur - shownPos) / 2.0f, 0.0f, 1.0f);
      }
      for (int i = 0; i < 12; i++) {
        float target = barsStale ? 0.0f : visualizerBars[i] * rampFactor * endFactor;
        if (target > displayBars[i]) {
          displayBars[i] = target;
        } else {
          displayBars[i] -= BAR_FALL;
          if (displayBars[i] < target) displayBars[i] = target;
        }
        if (displayBars[i] < 0) displayBars[i] = 0;
        int barH = map((int)displayBars[i], 0, 32, 0, 16);
        display.fillRect(i * 10 + 4, 64 - barH, 7, barH, SSD1306_WHITE);
      }
    } else {
      drawCenteredText(currentH + ":" + currentM, 30, 3);
    }
  }
  display.display();
}
