/** Local design preferences only. Never stores account, task or report content. */
export const DESIGN_SETTINGS_KEY='design-settings-v1';
export const DEFAULT_DESIGN_SETTINGS=Object.freeze({version:1,language:'zh',palette:'paper',density:'comfortable',readingWidth:640,textSize:18,motion:'system'});
const fields=Object.keys(DEFAULT_DESIGN_SETTINGS),editable=fields.filter(key=>key!=='version');
const enums={language:['zh','en'],palette:['paper','mineral','plum'],density:['comfortable','compact'],motion:['system','reduced']};
export function settingsErrors(value){
 const errors={};if(!value||typeof value!=='object'||Array.isArray(value))return {model:'object'};
 for(const key of fields)if(!Object.hasOwn(value,key))errors[key]='missing';if(value.version!==1)errors.version='version';if(Object.keys(value).some(key=>!fields.includes(key)))errors.model='unknown-field';
 for(const [key,options] of Object.entries(enums))if(!options.includes(value[key]))errors[key]='enum';
 for(const [key,min,max] of [['readingWidth',560,840],['textSize',16,22]])if(typeof value[key]!=='number'||!Number.isFinite(value[key])||value[key]<min||value[key]>max)errors[key]='range';
 return errors;
}
export function validateDesignSettings(value){const errors=settingsErrors(value);if(Object.keys(errors).length){const error=new TypeError('Invalid explicit design settings');error.fields=errors;throw error;}return {...value};}
export function loadDesignSettings(storage){
 let raw;try{raw=storage.getItem(DESIGN_SETTINGS_KEY);}catch{return {status:'unavailable',value:{...DEFAULT_DESIGN_SETTINGS}};}
 if(raw===null)return {status:'empty',value:{...DEFAULT_DESIGN_SETTINGS}};
 try{return {status:'saved',value:validateDesignSettings(JSON.parse(raw))};}catch{return {status:'invalid',value:{...DEFAULT_DESIGN_SETTINGS}};}
}
export function createSettingsState(saved=DEFAULT_DESIGN_SETTINGS){const value=validateDesignSettings(saved);return {saved:value,draft:{...value}};}
export function editSetting(state,key,value){if(!editable.includes(key))throw new TypeError('Unknown editable settings field');return {...state,draft:{...state.draft,[key]:value}};}
export function settingsDirty(state){return fields.some(key=>!Object.is(state.draft[key],state.saved[key]));}
export function undoSettings(state){return {...state,draft:{...state.saved}};}
/** Reset changes the draft; persistence still requires Save. */
export function resetSettings(state){return {...state,draft:{...DEFAULT_DESIGN_SETTINGS}};}
export function saveSettingsDraft(storage,state){
 const errors=settingsErrors(state.draft);if(Object.keys(errors).length)return {status:'invalid',errors,state};
 const value=validateDesignSettings(state.draft);
 try{storage.setItem(DESIGN_SETTINGS_KEY,JSON.stringify(value));}catch{return {status:'unavailable',errors:{},state};}
 return {status:'saved',errors:{},state:createSettingsState(value)};
}
