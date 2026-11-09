#include "web_mode.h"
#include "web_config.h"
#include "ota_config.h"
#include "web_assets.h"
#include <Preferences.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <Update.h>
#include <esp_system.h>
#include <atomic>
#include <algorithm>

namespace {
// Preserve the previous firmware's credential layout and namespace.
struct Config { uint32_t magic; uint8_t wifi; char ssid[33]; char password[65]; };
constexpr uint32_t MAGIC=0x45434731;
Config config{};
WebServer http(80); DNSServer dns;
bool ap=false, stayAP=false, connecting=false, stationReady=false, candidate=false;
bool triple=false, countArmed=false, armed=false, otaStarted=false;
uint32_t bootAt=0, connectAt=0, retryAt=0, apCloseAt=0, restartAt=0, armAt=0;
String csrf, pendingSSID, pendingPassword, networkMessage, apName, otaMessage="ECG_RUNNING";
std::atomic<bool> updating{false};
bool uploadOK=false, uploadAllowed=false; size_t uploaded=0, expected=0;
uint8_t imageHeader[24]; size_t headerUsed=0;
struct Entry { uint32_t seq, us; int16_t raw; };
constexpr uint32_t RING_SIZE=4096;
Entry ring[RING_SIZE]; uint32_t written=0,bootId=0;
portMUX_TYPE ringLock=portMUX_INITIALIZER_UNLOCKED;
String quote(const String &s){String out="\"";for(size_t i=0;i<s.length();++i){uint8_t c=s[i];if(c=='"'||c=='\\'){out+='\\';out+=char(c);}else if(c<32){char b[7];snprintf(b,sizeof(b),"\\u%04x",c);out+=b;}else out+=char(c);}return out+'"';}
void noCache(){http.sendHeader("Cache-Control","no-store");http.sendHeader("X-Content-Type-Options","nosniff");}
bool keyOK(){return strlen(OTA_TOKEN)==16 && http.header("X-ECG-Key")==OTA_TOKEN;}
bool authorized(){if(keyOK())return true;noCache();http.send(401,"text/plain","Enter the device access key (OTA_TOKEN).");return false;}
bool setupAuth(){if(ap && http.arg("csrf")==csrf)return true;return authorized();}
void clearCount(){Preferences p;if(p.begin("ecg-boot",false)){p.putUChar("count",0);p.end();}countArmed=false;}
void startAP(){
 if(ap)return;
 WiFi.mode(WIFI_AP_STA);
 WiFi.softAPConfig(IPAddress(192,168,4,1),IPAddress(192,168,4,1),IPAddress(255,255,255,0));
 char name[32];snprintf(name,sizeof(name),"ECG-Setup-%04X",unsigned(ESP.getEfuseMac()&0xffff));apName=name;
 if(!WiFi.softAP(name,SETUP_AP_PASSWORD)){networkMessage="Could not start hotspot";return;}
 ap=true;stayAP=false;dns.start(53,"*",WiFi.softAPIP());
}
void connectTo(const String &ssid,const String &password,bool isCandidate){
 WiFi.scanDelete();WiFi.disconnect(false,false);WiFi.mode(ap?WIFI_AP_STA:WIFI_STA);
 WiFi.setAutoReconnect(false);WiFi.begin(ssid.c_str(),password.c_str());
 connecting=true;candidate=isCandidate;connectAt=millis();networkMessage="Connecting…";
}
void failUpload(const String &message){Update.abort();uploadAllowed=false;uploadOK=false;updating=false;otaMessage=message;}
void uploadChunk(){
 HTTPUpload &u=http.upload();
 if(u.status==UPLOAD_FILE_START){
  uploadOK=false;uploadAllowed=false;uploaded=0;headerUsed=0;
  if(!keyOK()||!armed||updating.load()){otaMessage="OTA_REJECTED";return;}
  expected=strtoul(http.header("X-Image-Size").c_str(),nullptr,10);
  if(expected<24||expected>0x1e0000){otaMessage="OTA_BAD_SIZE";return;}
  updating=true;uploadAllowed=true;otaMessage="OTA_UPLOADING";
 }else if(u.status==UPLOAD_FILE_WRITE && uploadAllowed){
  if(uploaded+u.currentSize>expected){failUpload("OTA_SIZE_MISMATCH");return;}
  size_t pos=0;
  if(headerUsed<24){
   size_t n=std::min(size_t(24-headerUsed),u.currentSize);memcpy(imageHeader+headerUsed,u.buf,n);headerUsed+=n;pos=n;
   if(headerUsed==24){
    // ESP image magic + chip ID 9 (ESP32-S3). Reject other targets before flash writes.
    if(imageHeader[0]!=0xe9||imageHeader[12]!=9||imageHeader[13]!=0){failUpload("OTA_WRONG_CHIP");return;}
    if(!Update.begin(expected,U_FLASH)||Update.write(imageHeader,24)!=24){failUpload("OTA_BEGIN_FAILED");return;}
   }
  }
  if(pos<u.currentSize && Update.write(u.buf+pos,u.currentSize-pos)!=u.currentSize-pos){failUpload("OTA_WRITE_FAILED");return;}
  uploaded+=u.currentSize;armAt=millis();
 }else if(u.status==UPLOAD_FILE_END && uploadAllowed){
  if(headerUsed!=24||uploaded!=expected){failUpload("OTA_SIZE_MISMATCH");return;}
  uploadOK=Update.end(false);uploadAllowed=false;
  if(uploadOK){otaMessage="OTA_COMPLETE";restartAt=millis()+1500;}else failUpload("OTA_VERIFY_FAILED");
 }else if(u.status==UPLOAD_FILE_ABORTED){if(uploadAllowed)failUpload("OTA_ABORTED");}
}
void samples(bool binary){
 // Live viewing is public on the local network; updates remain authenticated.
 if(updating){http.send(503,"text/plain","Firmware update in progress");return;}
 static Entry batch[256];uint32_t requested=strtoul(http.arg("after").c_str(),nullptr,10),count,first,n,behind;
 portENTER_CRITICAL(&ringLock);count=written;behind=count-requested;
 if(!http.hasArg("after")||behind>0x7fffffffUL)behind=std::min(count,uint32_t(256));
 uint32_t available=std::min(behind,RING_SIZE);first=count-available;n=std::min(available,uint32_t(256));
 for(uint32_t i=0;i<n;i++)batch[i]=ring[(first+i)%RING_SIZE];portEXIT_CRITICAL(&ringLock);
 noCache();uint32_t overrun=behind>RING_SIZE?behind-RING_SIZE:0;
 if(binary){
  static uint8_t out[24+256*10];auto put=[&](size_t at,uint32_t v){for(int j=0;j<4;j++)out[at+j]=v>>(j*8);};
  put(0,0x33474345);put(4,bootId);put(8,first+n);put(12,count);put(16,overrun);put(20,n);
  for(uint32_t i=0;i<n;i++){size_t at=24+i*10;put(at,batch[i].seq);put(at+4,batch[i].us);out[at+8]=uint16_t(batch[i].raw);out[at+9]=uint16_t(batch[i].raw)>>8;}
  const size_t length = 24 + n * 10;
  http.setContentLength(length);
  http.send(200, "application/octet-stream", "");
  http.sendContent(reinterpret_cast<const char*>(out), length);
  return;
 }
 String body="{\"boot\":"+String(bootId)+",\"next\":"+String(first+n)+",\"latest\":"+String(count)+",\"overrun\":"+String(overrun)+",\"samples\":[";body.reserve(10000);
 for(uint32_t i=0;i<n;i++){if(i)body+=',';body+='[';body+=String(batch[i].seq)+','+String(batch[i].us)+','+String(batch[i].raw)+']';}body+="]}";http.send(200,"application/json",body);
}
void routes(){
 const char *headers[]={"X-ECG-Key","X-Image-Size"};http.collectHeaders(headers,2);
 http.on("/",HTTP_GET,[](){noCache();http.send_P(200,"text/html; charset=utf-8",ap&&!stayAP?PORTAL_HTML:MONITOR_HTML);});
 http.on("/monitor",HTTP_GET,[](){noCache();http.send_P(200,"text/html; charset=utf-8",MONITOR_HTML);});
 http.on("/setup",HTTP_GET,[](){noCache();http.send_P(200,"text/html; charset=utf-8",PORTAL_HTML);});
 http.on("/app.js",HTTP_GET,[](){noCache();http.send_P(200,"application/javascript",APP_JS);});
 http.on("/analysis-worker.js",HTTP_GET,[](){noCache();http.send_P(200,"application/javascript",WORKER_JS);});
 http.on("/data",HTTP_GET,[](){samples(false);});http.on("/samples",HTTP_GET,[](){samples(true);});
 http.on("/network",HTTP_GET,[](){
  if(!ap&&!authorized())return;
  noCache();http.send(200,"application/json",String("{\"ap\":")+(ap?"true":"false")+",\"connected\":"+(WiFi.status()==WL_CONNECTED?"true":"false")+",\"connecting\":"+(connecting?"true":"false")+",\"ssid\":"+quote(WiFi.status()==WL_CONNECTED?WiFi.SSID():String(config.ssid))+",\"ip\":"+quote(WiFi.localIP().toString())+",\"message\":"+quote(networkMessage)+",\"csrf\":"+quote(ap?csrf:String())+",\"ota\":"+quote(webOtaStatus())+"}");
 });
 http.on("/scan",HTTP_GET,[](){
  if(!ap&&!authorized())return;
  if(connecting||updating){http.send(409,"text/plain","Wait for current operation");return;}
  int n=WiFi.scanComplete();if(n==WIFI_SCAN_FAILED){WiFi.scanNetworks(true,true);http.send(202,"application/json","{\"scanning\":true}");return;}
  if(n==WIFI_SCAN_RUNNING){http.send(202,"application/json","{\"scanning\":true}");return;}
  String body="{\"networks\":[";for(int i=0;i<n&&i<40;i++){if(i)body+=',';body+="{\"ssid\":"+quote(WiFi.SSID(i))+",\"rssi\":"+String(WiFi.RSSI(i))+",\"open\":"+(WiFi.encryptionType(i)==WIFI_AUTH_OPEN?String("true"):String("false"))+"}";}body+="]}";WiFi.scanDelete();noCache();http.send(200,"application/json",body);
 });
 http.on("/join",HTTP_POST,[](){
  if(!setupAuth())return;
  if(updating||connecting){http.send(409,"text/plain","Operation already in progress");return;}
  String ssid=http.arg("ssid"),pass=http.arg("password");
  if(!ssid.length()||ssid.length()>32||pass.length()>63||(pass.length()>0&&pass.length()<8)){http.send(400,"text/plain","SSID: 1–32 bytes. WPA password: 8–63 characters, or empty for an open network.");return;}
  pendingSSID=ssid;pendingPassword=pass;stayAP=false;apCloseAt=0;stationReady=false;
  http.send(202,"text/plain","Connecting. Keep this page open; hotspot closes only after connection succeeds.");connectTo(ssid,pass,true);
 });
 http.on("/continue",HTTP_POST,[](){if(!setupAuth())return;if(!ap){http.send(409,"text/plain","Hotspot is not active");return;}if(updating){http.send(409);return;}
  WiFi.disconnect(false,false);connecting=false;candidate=false;stationReady=false;apCloseAt=0;stayAP=true;networkMessage="Operating on hotspot for this session";http.send(200,"text/plain","Open /monitor");});
 http.on("/ota/arm",HTTP_POST,[](){if(!authorized())return;if(updating){http.send(409);return;}webArmOta();http.send(200,"application/json","{\"armed\":true,\"seconds\":300}");});
 http.on("/ota/upload",HTTP_POST,[](){
  noCache();if(!keyOK()){http.send(401,"text/plain","Invalid device key");return;}
  http.send(uploadOK?200:400,"text/plain",uploadOK?"Firmware verified. Restarting…":otaMessage);
 },uploadChunk);
 http.onNotFound([](){if(ap){http.sendHeader("Location","http://192.168.4.1/");http.send(302,"text/plain","Open ECG setup");}else http.send(404,"text/plain","Not found");});
}
}
void webBoot(bool){
 bootAt=millis();bootId=esp_random();csrf=String(esp_random(),HEX)+String(esp_random(),HEX);
 config.magic=MAGIC;config.wifi=1;strlcpy(config.ssid,OTA_WIFI_SSID,sizeof(config.ssid));strlcpy(config.password,OTA_WIFI_PASSWORD,sizeof(config.password));
 Preferences p;if(p.begin("ecg-config",true)){Config saved{};if(p.getBytesLength("config")==sizeof(saved)&&p.getBytes("config",&saved,sizeof(saved))==sizeof(saved)&&saved.magic==MAGIC&&saved.ssid[32]==0&&saved.password[64]==0)config=saved;p.end();}
 auto reason=esp_reset_reason();if(reason==ESP_RST_POWERON||reason==ESP_RST_EXT){if(p.begin("ecg-boot",false)){uint8_t c=p.getUChar("count",0);triple=c>=2;p.putUChar("count",triple?0:c+1);p.end();countArmed=!triple;}}else clearCount();
}
void webBegin(){
 routes();WiFi.persistent(false);WiFi.mode(WIFI_STA);WiFi.setHostname("ecg");WiFi.setSleep(false);
 if(triple||!strlen(config.ssid))startAP();else connectTo(config.ssid,config.password,false);
 http.begin();retryAt=millis();
 ArduinoOTA.setHostname("ecg");ArduinoOTA.setPassword(OTA_TOKEN);ArduinoOTA.setPort(3232);
 ArduinoOTA.onStart([](){updating=true;otaMessage="OTA_UPLOADING";});
 ArduinoOTA.onError([](ota_error_t){updating=false;armed=false;otaMessage="OTA_ERROR";});
 ArduinoOTA.onEnd([](){otaMessage="OTA_COMPLETE";});
}
void webArmOta(){armed=true;armAt=millis();otaMessage="OTA_WAIT_WIFI";}
bool webUpdating(){return updating.load();}
String webOtaStatus(){if(updating)return otaMessage;if(armed&&(WiFi.status()==WL_CONNECTED||ap))return String("OTA_READY ")+(WiFi.status()==WL_CONNECTED?WiFi.localIP():WiFi.softAPIP()).toString();return otaMessage;}
void webLoop(){
 uint32_t now=millis();if(countArmed&&now-bootAt>=BOOT_WINDOW_MS)clearCount();
 if(restartAt&&int32_t(now-restartAt)>=0)ESP.restart();
 if(WiFi.status()==WL_CONNECTED){
  retryAt=now;
  if(!stationReady){
   connecting=false;stationReady=true;MDNS.end();MDNS.begin("ecg");MDNS.addService("http","tcp",80);
   networkMessage="Connected. Join this Wi-Fi and open http://ecg.local/ or http://"+WiFi.localIP().toString()+"/";
   if(candidate){Config next{};next.magic=MAGIC;next.wifi=1;strlcpy(next.ssid,pendingSSID.c_str(),sizeof(next.ssid));strlcpy(next.password,pendingPassword.c_str(),sizeof(next.password));Preferences p;bool ok=false;if(p.begin("ecg-config",false)){ok=p.putBytes("config",&next,sizeof(next))==sizeof(next);p.end();}if(ok)config=next;else networkMessage+=" Settings could not be saved; configure again after reboot.";candidate=false;pendingPassword="";}
   if(ap&&!stayAP)apCloseAt=now+15000;
  }
 }else{
  if(stationReady){stationReady=false;MDNS.end();connecting=true;connectAt=now;WiFi.reconnect();}
  if(connecting&&now-connectAt>=WIFI_CONNECT_TIMEOUT_MS){WiFi.disconnect(false,false);connecting=false;candidate=false;pendingPassword="";apCloseAt=0;networkMessage="Could not connect. Check SSID/password or continue on hotspot.";startAP();retryAt=now;}
  if(ap&&!stayAP&&!connecting&&strlen(config.ssid)&&now-retryAt>60000){retryAt=now;connectTo(config.ssid,config.password,false);}
 }
 if(apCloseAt&&WiFi.status()==WL_CONNECTED&&int32_t(now-apCloseAt)>=0&&!updating){dns.stop();WiFi.softAPdisconnect(false);WiFi.mode(WIFI_STA);ap=false;apCloseAt=0;}
 if(ap)dns.processNextRequest();
 http.handleClient();
 // HTTP handlers can set armAt after the time captured at loop entry.
 // Refresh now to avoid unsigned underflow expiring a newly armed session.
 now=millis();
 if(armed&&!otaStarted&&(ap||WiFi.status()==WL_CONNECTED)){ArduinoOTA.begin();otaStarted=true;}
 if(armed&&!updating&&now-armAt>300000){armed=false;otaMessage="ECG_RUNNING";}
 if(!armed&&otaStarted&&!updating){ArduinoOTA.end();otaStarted=false;}
 if(armed&&otaStarted&&!updating)ArduinoOTA.handle();
}
void webPublish(uint32_t seq,uint32_t us,int16_t raw){portENTER_CRITICAL(&ringLock);ring[written%RING_SIZE]={seq,us,raw};++written;portEXIT_CRITICAL(&ringLock);}
