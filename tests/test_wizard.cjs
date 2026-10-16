const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const els=new Map();const el=id=>{if(!els.has(id))els.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,dataset:{},scrollIntoView(){}});return els.get(id)};
const ctx={console,setTimeout,clearTimeout,AbortController,URL,Blob,document:{querySelector:el,querySelectorAll:()=>[],createElement:()=>({})},fetch:async()=>({json:async()=>({})})};vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/app.js','utf8'),ctx);
assert.equal(el('#photoStep').hidden,false);assert.equal(el('#basket').hidden,true);assert.equal(vm.runInContext('goToStep(2)',ctx),false);
vm.runInContext("basket=[{name:'테스트 제품',ingredients:[]}];",ctx);assert.equal(vm.runInContext('goToStep(2)',ctx),true);assert.equal(el('#basket').hidden,false);assert.equal(el('#photoStep').hidden,true);
assert.equal(vm.runInContext('goToStep(3)',ctx),false);vm.runInContext('lastReport={};goToStep(3)',ctx);assert.equal(el('#resultStep').hidden,false);assert.equal(el('#basket').hidden,true);
vm.runInContext('goToStep(1)',ctx);assert.equal(el('#photoStep').hidden,false);
vm.runInContext("photoGroups=[{status:'choice'}]",ctx);assert.equal(vm.runInContext('goToStep(2)',ctx),false);
const html=fs.readFileSync('static/index.html','utf8');assert(html.indexOf('id="productPicker"')<html.indexOf('id="basket"'));assert(html.indexOf('id="batchChoices"')<html.indexOf('id="basket"'));assert.equal((html.match(/id="demo"/g)||[]).length,1);
console.log('PASS: 초기 화면·단계 이동·결과 선행 차단·뒤로가기·제품 선택 위치');

vm.runInContext("photoGroups=[{id:1,status:'choice'},{id:2,status:'applied'}];removePhotoLog(1)",ctx);
assert.equal(vm.runInContext('photoGroups.length',ctx),1);assert.equal(vm.runInContext('basket.length',ctx),1,'내역 삭제는 제품 유지');
vm.runInContext('lastReport={};removeStepProduct(0)',ctx);assert.equal(vm.runInContext('basket.length',ctx),0);assert.equal(vm.runInContext('lastReport',ctx),null,'제품 제외 시 결과 무효화');
vm.runInContext("basket=[{name:'보존',ingredients:[]}];busy=true;removePhotoLog(2);removeStepProduct(0);busy=false",ctx);assert.equal(vm.runInContext('photoGroups.length',ctx),1);assert.equal(vm.runInContext('basket.length',ctx),1);
console.log('PASS: 내역 삭제·제품 제외 분리·결과 무효화·처리 중 변경 차단');
