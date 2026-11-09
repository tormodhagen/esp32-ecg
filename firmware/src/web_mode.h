#pragma once
#include <Arduino.h>
void webBoot(bool unused);
void webBegin();
void webLoop();
void webPublish(uint32_t sequence, uint32_t timestamp, int16_t raw);
void webArmOta();
bool webUpdating();
String webOtaStatus();
