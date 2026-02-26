#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <Wire.h>
#include <U8g2lib.h>          
#include <VL53L0X.h>       
#include "OneButton.h"        
#include <ArduinoJson.h>

// --- Config ---
const char* ssid = "****";
const char* password = "****";
const char* serverUrl = "http://****:**/api/add-entry"; // YOUR SERVER'S IP

#define BUTTON_PIN 5 // D1 is GPIO5
#define THRESHOLD_MM 200 // Distance change to trigger a pullup (20cm)
#define XSHUT_PIN 13 // D7 is GPIO13

// --- Hardware ---
// 1. OLED on Software I2C (Pins D5/12 and D6/14)
U8G2_SSD1306_128X64_NONAME_F_SW_I2C u8g2(U8G2_R0, /* clock=*/ 12, /* data=*/ 14, U8X8_PIN_NONE);

// 2. Sensor using Pololu Library
VL53L0X sensor;

// 3. Button
OneButton button(BUTTON_PIN, true); // true = active LOW

// --- State Machine ---
enum State { PREP, WORKOUT, REST, DONE };
State currentState = PREP;

// --- Session Data ---
struct SetData {
  int reps;
  unsigned long duration_sec;
  unsigned long rest_after_sec;
};
SetData workoutSets[15]; 
int currentSetIndex = 0;
int totalSessionReps = 0;

unsigned long stateStartTime = 0;
int currentReps = 0;
int baseDistance = 0;
bool isPullupUp = false; 

void setup() {
  Serial.begin(115200);
  
  // --- HARDWARE RESET THE SENSOR ---
  pinMode(XSHUT_PIN, OUTPUT);
  digitalWrite(XSHUT_PIN, LOW);  // Turn sensor off
  delay(20);
  digitalWrite(XSHUT_PIN, HIGH); // Turn sensor on
  delay(20);                     // Give it a moment to boot
  
  // Start Hardware I2C for the Sensor on D2(GPIO4) and D3(GPIO0)
  Wire.begin(4, 0); 

  // Init Screen (Uses SW I2C internally)
  u8g2.begin();
  u8g2.enableUTF8Print();
  updateScreen("BOOTING...", "Init Hardware");
  
  // Connect to WiFi in the background while prepping/working out
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  // Init Sensor
  sensor.setTimeout(500);
  if (!sensor.init()) {
    updateScreen("ERROR", "Sensor Dead");
    while(1);
  }
  
  // Setup Button callbacks
  button.setPressMs(1000); // 1000 milliseconds = 1 second hold
  button.attachClick(handleSingleClick);
  button.attachLongPressStart(handleLongPress);

  // Jump straight into the first prep phase
  currentSetIndex = 0;
  totalSessionReps = 0;
  stateStartTime = millis();
  currentState = PREP;
}

void loop() {
  button.tick(); 

  switch (currentState) {
    case PREP: handlePrepState(); break;
    case WORKOUT: handleWorkoutState(); break;
    case REST: handleRestState(); break;
    case DONE: break; // Do nothing, wait for physical power off
  }
}

// --- State Handlers ---

void handlePrepState() {
  int secondsLeft = 3 - ((millis() - stateStartTime) / 1000);
  
  if (secondsLeft <= 0) {
    // Take a few dummy readings to clear any stale data
    sensor.readRangeSingleMillimeters(); 
    sensor.readRangeSingleMillimeters();
    
    // Establish the "Tripwire" distance to the opposite wall
    baseDistance = sensor.readRangeSingleMillimeters();
    
    currentReps = 0;
    isPullupUp = false; // Reset the flag
    stateStartTime = millis();
    currentState = WORKOUT;
    updateScreen("GO!", "Reps: 0");
  } else {
    char buf[16];
    sprintf(buf, "Starting in %d...", secondsLeft);
    updateScreen("Get Ready!", buf);
  }
}

void handleWorkoutState() {
  int currentDist = sensor.readRangeSingleMillimeters();
  
  // Pololu returns 8190 for timeout/out of range, so we ignore anything above 8000
  if (!sensor.timeoutOccurred() && currentDist < 8000) { 
    
    // Detect pulling UP (Beam is BROKEN)
    // If the distance suddenly drops by more than the THRESHOLD (e.g. 20cm)
    if (currentDist < (baseDistance - THRESHOLD_MM) && !isPullupUp) {
      isPullupUp = true;
      currentReps++;
      totalSessionReps++;
      
      char buf[16];
      sprintf(buf, "Reps: %d", currentReps);
      updateScreen("WORKOUT", buf);
    }
    
    // Detect going DOWN (Beam is RESTORED)
    // We use a slight offset (THRESHOLD_MM / 2) to prevent flickering 
    // if you are hovering right on the edge of the beam.
    else if (currentDist > (baseDistance - (THRESHOLD_MM / 2)) && isPullupUp) {
      isPullupUp = false;
    }
  }
}

void handleRestState() {
  unsigned long restingFor = (millis() - stateStartTime) / 1000;
  char buf[16];
  sprintf(buf, "Resting: %lds", restingFor);
  updateScreen("REST MODE", buf);
}

// --- Button Logic ---

void handleSingleClick() {
  if (currentState == WORKOUT) {
    workoutSets[currentSetIndex].reps = currentReps;
    workoutSets[currentSetIndex].duration_sec = (millis() - stateStartTime) / 1000;
    stateStartTime = millis();
    currentState = REST;
  }
  else if (currentState == REST) {
    workoutSets[currentSetIndex].rest_after_sec = (millis() - stateStartTime) / 1000;
    currentSetIndex++;
    stateStartTime = millis();
    currentState = PREP;
  }
}

void handleLongPress() {
  // Only allow ending the session if we are actually doing a workout or resting
  if (currentState == WORKOUT || currentState == REST) {
    
    // If we double-click mid-set, we need to save the current reps/duration right now
    if (currentState == WORKOUT) {
      workoutSets[currentSetIndex].reps = currentReps;
      workoutSets[currentSetIndex].duration_sec = (millis() - stateStartTime) / 1000;
    }
    
    // In either case, this is the final set, so rest time after it is 0.
    workoutSets[currentSetIndex].rest_after_sec = 0; 
    
    // Move the index forward to lock in this final set
    currentSetIndex++; 
    
    // Stop everything, sync, and halt
    updateScreen("SYNCING...", "Connecting...");
    sendDataToPi();
    
    // Halt operations and prompt user to flip the physical switch
    currentState = DONE;
    updateScreen("ALL DONE", "Power Off Now");
  }
}

// --- Helpers ---

void updateScreen(const char* line1, const char* line2) {
  u8g2.clearBuffer();
  
  // Top Header Line (Always small)
  u8g2.setFont(u8g2_font_ncenB08_tr);
  u8g2.drawStr(0, 20, line1);
  
  // Bottom Main Line (Dynamically sizes based on text length)
  if (strlen(line2) > 10) {
    u8g2.setFont(u8g2_font_ncenB10_tr); // Smaller font for long strings like "Connecting..."
  } else {
    u8g2.setFont(u8g2_font_ncenB14_tr); // Big font for short strings like "Reps: 12"
  }
  
  u8g2.drawStr(0, 50, line2);
  u8g2.sendBuffer();
}

void sendDataToPi() {
  // Since WiFi started connecting in setup(), it should be ready, but we will wait just in case
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    WiFiClient client;
    HTTPClient http;
    http.begin(client, serverUrl);
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<512> doc;
    doc["total_reps"] = totalSessionReps;
    JsonArray sets = doc.createNestedArray("sets");
    
    for (int i = 0; i < currentSetIndex; i++) {
      JsonObject setObj = sets.createNestedObject();
      setObj["reps"] = workoutSets[i].reps;
      setObj["duration_seconds"] = workoutSets[i].duration_sec;
      setObj["rest_time_after"] = workoutSets[i].rest_after_sec;
    }

    String requestBody;
    serializeJson(doc, requestBody);
    
    int httpResponseCode = http.POST(requestBody);
    
    if (httpResponseCode > 0) {
      updateScreen("SUCCESS!", "Data Sent");
      delay(2000); // Give the user time to see the success message
    } else {
      updateScreen("API ERROR", "Send Failed");
      delay(3000); 
    }
    http.end();
  } else {
    updateScreen("WIFI ERROR", "No Connection");
    delay(3000); 
  }
  
  // Turn off WiFi radio completely
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}
