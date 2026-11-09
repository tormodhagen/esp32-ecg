const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map();
const ctx=new Proxy({}, {get:()=>()=>{}});
function node(id){if(!nodes.has(id))nodes.set(id,{value:({gain:1,span:8,mode:'raw'})[id]||'',checked:false,style:{},classList:{add(){},remove(){}},clientWidth:800,clientHeight:430,getContext:()=>ctx});return nodes.get(id)}
const sandbox={Worker:class {postMessage(){}},DataView,Uint8Array,Date,document:{getElementById:node,addEventListener(){}},window:{addEventListener(){}},navigator:{},localStorage:{getItem:()=>null},requestAnimationFrame(){},Float64Array,setInterval(){},setTimeout(){},performance:{now:()=>100},console};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__dirname+'/../firmware/web/app.js','utf8')+'\nglobalThis.api={state,ingest,filterRows,calibrate,detect,decodeSamples,recordMetadata,envelope,visibleRows};',sandbox);
const {state,ingest,filterRows,calibrate,detect,decodeSamples,recordMetadata}=sandbox.api;
function packet(samples,boot=1){return {boot,next:samples.length,overrun:0,samples}}
ingest(packet([[10,4294967000,100],[11,704,200],[14,3704,300]]));
assert(Math.abs(state.time-.004)<1e-9);assert.equal(state.lost,2);assert.equal(state.rows[2].v,.0375);
state.recording=true;ingest(packet([[1,1000,0]],2));assert.equal(state.recording,false);assert.equal(state.rows.length,1);assert.equal(state.time,0);
const sine=Array.from({length:860*15},(_,i)=>({t:i/860,v:.8*Math.sin(2*Math.PI*i/860)+.1}));
assert(Math.abs(calibrate(sine,1,10)-160)<1e-6);
const filtered=filterRows(sine),last=sine.at(-1).t;
assert(filtered.filter(r=>r.t>last-5).every(r=>Number.isNaN(r.y)));
assert(filtered.filter(r=>r.t>4&&r.t<8).every(r=>Number.isFinite(r.y)));
const rms=Math.sqrt(filtered.filter(r=>r.t>4&&r.t<8).reduce((a,r)=>a+r.y*r.y,0)/(4*860-1));assert(rms>.50&&rms<.60);
const gapped=sine.filter(r=>r.t<7||r.t>7.1);assert.throws(()=>calibrate(gapped,1,10),/Datagap/);
const ecg=Array.from({length:860*15},(_,i)=>{const t=i/860,d=t-Math.round(t);return {t,v:.5*Math.exp(-d*d/.0003)-.1*Math.exp(-((d-.045)**2)/.0005)}});
const detection=detect(ecg);assert(Math.abs(detection.bpm-60)<1);assert(detection.beats.length>=12);
console.log('PASS: timestamp wrap, packet loss, reset recording, calibration, delayed filter, gaps, 60 BPM');

for(const f of [.5,1,7.3,40])for(const phase of [0,.7,2.8])for(const offset of [0,1.5]){
 const wave=Array.from({length:Math.ceil(842.7*15)},(_,i)=>{const t=i/842.7;return {t,v:offset+.53*Math.sin(2*Math.PI*f*t+phase)+.0005*t}});
 assert(Math.abs(calibrate(wave,f,10)-106)<.01);
 const half=wave.map(r=>({t:r.t,v:offset+Math.max(0,r.v-offset-.0005*r.t)+.0005*r.t}));
 assert(Math.abs(calibrate(half,f,10,true)-106)<.02);
 assert.throws(()=>calibrate(half,f,10),/sinustilpasning/);
}
console.log('PASS: offset and positive-half calibration, multiple frequencies and phases');

const packetBytes=new ArrayBuffer(34),dv=new DataView(packetBytes);
[0x33474345,123,1,1,0,1].forEach((n,i)=>dv.setUint32(4*i,n,true));dv.setUint32(24,7,true);dv.setUint32(28,1190,true);dv.setInt16(32,-101,true);
assert.equal(sandbox.api.decodeSamples(packetBytes).samples[0][2],-101);
assert.throws(()=>sandbox.api.decodeSamples(new ArrayBuffer(2)),/Invalid/);
node('gain').value=431.646;node('mv').checked=true;
const meta=sandbox.api.recordMetadata();assert.equal(meta.analog_gain_v_per_v,431.646);assert.equal(meta.gain_applied_to_voltage_column,false);assert.equal(meta.voltage_units,'V');
console.log('PASS: binary sample decoding and raw-voltage calibration metadata');

const dense=Array.from({length:17200},(_,i)=>({t:i/860,v:i===8000?10:0}));
const reduced=sandbox.api.envelope(dense,500,false,0,20);
assert(reduced.length<=2004);assert(reduced.some(r=>r.v===10));
const gap=dense.filter(r=>r.t<5||r.t>5.2);
assert(sandbox.api.envelope(gap,500,false,0,20).some(r=>r.gap));
assert.equal(sandbox.api.visibleRows(dense,2,3).length,861);
console.log('PASS: peak-preserving draw reduction, gap retention, indexed visible range');
