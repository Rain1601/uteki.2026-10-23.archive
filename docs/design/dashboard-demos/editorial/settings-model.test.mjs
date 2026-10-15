import test from 'node:test';import assert from 'node:assert/strict';
import {DESIGN_SETTINGS_KEY,DEFAULT_DESIGN_SETTINGS,validateDesignSettings,settingsErrors,loadDesignSettings,createSettingsState,editSetting,settingsDirty,undoSettings,resetSettings,saveSettingsDraft} from './settings-model.mjs';
const memory=()=>{const records=new Map();return {records,getItem:key=>records.get(key)??null,setItem:(key,value)=>records.set(key,value)};};
test('explicit versioned preferences reject missing fields, unknown fields and unsupported enum',()=>{
 for(const key of Object.keys(DEFAULT_DESIGN_SETTINGS)){const value={...DEFAULT_DESIGN_SETTINGS};delete value[key];assert.throws(()=>validateDesignSettings(value),TypeError,key);}
 for(const value of [null,[],{...DEFAULT_DESIGN_SETTINGS,task:'secret'},{...DEFAULT_DESIGN_SETTINGS,version:2},{...DEFAULT_DESIGN_SETTINGS,language:'fr'},{...DEFAULT_DESIGN_SETTINGS,palette:'dark'},{...DEFAULT_DESIGN_SETTINGS,density:'dense'},{...DEFAULT_DESIGN_SETTINGS,motion:'always'}])assert.throws(()=>validateDesignSettings(value),TypeError);
});
test('numeric preference ranges preserve zero/NaN errors and accept exact bounds',()=>{
 for(const [key,min,max] of [['readingWidth',560,840],['textSize',16,22]]){for(const value of [min,max])assert.equal(validateDesignSettings({...DEFAULT_DESIGN_SETTINGS,[key]:value})[key],value);for(const value of [min-1,max+1,NaN,Infinity,null,String(min),0])assert.equal(settingsErrors({...DEFAULT_DESIGN_SETTINGS,[key]:value})[key],'range');}
});
test('draft edit, undo and reset keep saved settings separate',()=>{
 const saved={...DEFAULT_DESIGN_SETTINGS,palette:'plum',readingWidth:720};let state=createSettingsState(saved);state=editSetting(state,'palette','mineral');assert(settingsDirty(state));assert.equal(state.saved.palette,'plum');assert.equal(undoSettings(state).draft.palette,'plum');assert(!settingsDirty(undoSettings(state)));
 state=resetSettings(state);assert.equal(state.draft.palette,'paper');assert.equal(state.saved.palette,'plum');assert(settingsDirty(state));assert.throws(()=>editSetting(state,'version',2),/Unknown editable/);
});
test('successful save writes preference fields only and updates saved baseline',()=>{
 const storage=memory();const state=editSetting(createSettingsState(),'textSize',20),result=saveSettingsDraft(storage,state);assert.equal(result.status,'saved');assert(!settingsDirty(result.state));assert.equal(result.state.saved.textSize,20);assert.deepEqual(Object.keys(JSON.parse(storage.records.get(DESIGN_SETTINGS_KEY))),Object.keys(DEFAULT_DESIGN_SETTINGS));assert.equal(loadDesignSettings(storage).value.textSize,20);
});
test('validation and storage failures never claim saved or overwrite saved baseline',()=>{
 let called=false;const storage={setItem(){called=true;throw Error('Quota');}};let state=editSetting(createSettingsState(),'readingWidth',NaN);assert.equal(saveSettingsDraft(storage,state).status,'invalid');assert(!called);state=editSetting(state,'readingWidth',700);const result=saveSettingsDraft(storage,state);assert.equal(result.status,'unavailable');assert.equal(result.state,state);assert.equal(result.state.saved.readingWidth,640);assert(settingsDirty(result.state));
});
test('invalid persisted record and unavailable storage are explicit; no silent successful load',()=>{
 const storage=memory();assert.equal(loadDesignSettings(storage).status,'empty');storage.records.set(DESIGN_SETTINGS_KEY,'{broken');assert.equal(loadDesignSettings(storage).status,'invalid');storage.records.set(DESIGN_SETTINGS_KEY,JSON.stringify({...DEFAULT_DESIGN_SETTINGS,task:'discard'}));assert.equal(loadDesignSettings(storage).status,'invalid');assert.equal(loadDesignSettings({getItem(){throw Error('Denied')}}).status,'unavailable');
});
test('inherited preference fields cannot satisfy an explicit saved record',()=>{const value=Object.create(DEFAULT_DESIGN_SETTINGS);assert.throws(()=>validateDesignSettings(value),TypeError);});
