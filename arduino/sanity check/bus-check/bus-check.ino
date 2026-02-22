#include <Wire.h>

void setup() {
  Serial.begin(115200);
  while (!Serial); 
  
  Serial.println("\n--- Scanning D2 and D3 ---");
  
  // D2 is GPIO4 (SDA), D3 is GPIO0 (SCL)
  Wire.begin(4, 0); 
}

void loop() {
  byte error, address;
  int nDevices = 0;

  Serial.println("Scanning...");

  for(address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("Device found at address 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
      nDevices++;
    }
  }
  
  if (nDevices == 0) {
    Serial.println("Nothing found. Sensor is dead.");
  } else {
    Serial.println("Scan complete.\n");
  }

  delay(3000);
}