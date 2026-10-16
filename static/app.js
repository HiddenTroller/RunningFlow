const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = '', busy = false, photoId = null, candidates = [], selected = null;
let basket = [], lastReport = null, page = 1, searchName = '', demoMode = false;
function recoveryHint(message) {
  if (/만료|확인 정보/.test(message)) return '목록의 ‘공식 정보 다시 확인’을 누르세요. 사진은 다시 전송하지 않습니다.';
  if (/403|인증|키|한도/.test(message)) return '분석 상세의 연결 상태와 API 인증·사용량을 확인한 뒤 다시 시도하세요.';
  if (/초과|시간|네트워크|fetch|Failed/.test(message)) return '연결을 확인하고 잠시 후 재시도하세요. 제품 목록과 수량은 유지됩니다.';
  if (/함량|단위|충돌/.test(message)) return '제품·제형·함량을 확인하세요. 불명확한 제품은 제외하거나 추가 관리에서 근거를 보완할 수 있습니다.';
  return '입력값을 확인하고 다시 시도해 주세요.';
}
const say = message => { $('#status').textContent = message; };
function showError(error) {
  const message = error?.message || '요청을 완료하지 못했습니다.';
  say(message + ' ' + recoveryHint(message));
  $('#errorHelp').textContent = message + ' ' + recoveryHint(message);
  $('#errorHelp').hidden = false;
}
const SESSION_KEY = 'learningflow-session-v1';
let restoring = false;
function saveSession() {
  if (restoring || typeof sessionStorage === 'undefined') return;
  try {
    sessionStorage.setItem(SESSION_KEY,JSON.stringify({version:1,at:Date.now(),demo:demoMode,
      items:basket.map(p=>({code:p.code,name:p.name,quantity:p.quantity,approval_id:p.approval_id})),
      photo_groups:photoGroups.map(g=>({id:g.id,filename:g.filename,status:g.status==='processing'?'error':g.status,message:g.status==='processing'?'분석이 중단됐습니다. 해당 사진을 다시 선택해 분석하세요.':g.message,result:g.result?{photo_id:g.result.photo_id,candidates:(g.result.candidates || []).map(c=>({candidate_id:c.candidate_id,product:{ITEM_SEQ:c.product.ITEM_SEQ,ITEM_NAME:c.product.ITEM_NAME}}))}:null})),
      profile:{ageYears:$('#ageYears').value,weightKg:$('#weightKg').value},mode:$('#mode').value,quantity_intent:$('#quantityIntent').value}));
  } catch { $('#saveNotice').textContent = '브라우저 저장 공간을 사용할 수 없어 새로고침 시 목록이 사라질 수 있습니다.'; }
}
async function restoreSession() {
  if (typeof sessionStorage === 'undefined') return;
  restoring = true;
  try {
    const raw=sessionStorage.getItem(SESSION_KEY);if (!raw)return;
    const saved=JSON.parse(raw);
    if(saved.version!==1 || !Array.isArray(saved.items) || saved.items.length>30 || Date.now()-saved.at>86400000) {
      sessionStorage.removeItem(SESSION_KEY);return;
    }
    if(Array.isArray(saved.photo_groups)) {
      photoGroups=saved.photo_groups.slice(-100).filter(g=>g && Number.isInteger(g.id) && typeof g.filename==='string' && ['choice','applied','error','empty'].includes(g.status) && (!g.result || Array.isArray(g.result.candidates)));
      nextGroupId=Math.max(0,...photoGroups.map(g=>g.id));renderBatchQueue();
    }
    for(const id of ['ageYears','weightKg']) $('#'+id).value=String(saved.profile?.[id] ?? '');
    $('#mode').value=['single','day'].includes(saved.mode)?saved.mode:'single';
    $('#quantityIntent').value=saved.quantity_intent==='taken'?'taken':'planned';
    updateIntentHelp();
    if (saved.demo) {
      const samples=await (await fetch('/sample.json',{cache:'no-store'})).json();
      basket=samples.filter(p=>saved.items.some(i=>i.code===p.code)).map(p=>({...p,quantity:saved.items.find(i=>i.code===p.code).quantity}));demoMode=true;
    } else if (saved.items.length) basket=(await api('/api/restore-basket',{items:saved.items})).items;
    renderBasket();
    if(basket.length) say('이전 목록과 입력값을 복원했습니다.' + (basket.some(p=>p.restored_pending)?' 공식 정보를 다시 확인해 주세요.':''));
  } catch { $('#saveNotice').textContent='저장된 목록을 복원하지 못했습니다. 새로고침하거나 사진을 다시 분석해 주세요.'; }
  finally { restoring=false; }
}


async function api(path, data) {
  if (busy) throw Error('진행 중인 요청을 기다려 주세요.');
  busy = true;
  const processingMessage = path === '/api/resolve-official' ? '공식 성분과 함량을 확인하고 있습니다…' : path === '/api/product-support' ? '제품 주의사항을 불러오고 있습니다…' : '요청을 처리하고 있습니다…';
  say(processingMessage);
  document.querySelectorAll('button').forEach(b => { b.dataset.disabledBefore = String(b.disabled); b.disabled = true; });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path === '/api/product-support' ? 12000 : path === '/api/resolve-official' ? 30000 : 180000);
  try {
    const response = await fetch(path, {method:'POST', signal:controller.signal, cache:'no-store', headers:{'Content-Type':'application/json','X-App-Token':token}, body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) {
      if(path === '/api/evaluate' && /만료|확인 정보/.test(result.error || '')) {
        basket=basket.map(p=>({...p,pending:true,restored_pending:true,comparison_warnings:['공식 확인이 만료됐습니다. 다시 확인해 주세요.']}));renderBasket();
      }
      throw Error(result.error || '요청을 처리하지 못했습니다.');
    }
    $('#errorHelp').hidden=true;
    return result;
  } catch (error) {
    if (error.name === 'AbortError') throw Error('응답 시간이 초과되었습니다. 잠시 후 다시 적용하세요.');
    throw error;
  } finally {
    clearTimeout(timer);
    busy = false;
    if ($('#status').textContent === processingMessage) say('');
    document.querySelectorAll('button').forEach(b => { b.disabled = b.dataset.disabledBefore === 'true'; });
    updateProfileControls();
  }
}

async function start() {
  try {
    const result = await (await fetch('/api/status', {cache:'no-store'})).json();
    token = result.token;
    const checkedAt = result.checked_at ? new Date(result.checked_at).toLocaleTimeString('ko-KR') : '';
    $('#connection').textContent = `설정 ${result.requested_config_id}번 고정 / 연결 확인 ${checkedAt} / 식약처 키 ${result.mfds_ready ? '입력됨' : '미입력'} / Upstage 키 ${result.studio_ready ? '입력됨' : '미입력'}${result.legacy_config_ignored ? ' / 환경 변수의 다른 설정 번호는 무시됨' : ''}`;
  } catch { say('Python 서버 연결을 확인하세요.'); }
}

function profileIsComplete() {
  const age = $('#ageYears').value.trim(), weight = $('#weightKg').value.trim();
  return age !== '' && Number.isFinite(Number(age)) && Number(age)>=0 && Number(age)<=130
    && weight !== '' && Number.isFinite(Number(weight)) && Number(weight)>0 && Number(weight)<=500;
}
function updateProfileControls() {
  const complete = profileIsComplete();
  $('#evaluate').disabled = busy || (typeof batchRunning !== 'undefined' && batchRunning) || !complete;
  $('#profileRequired').textContent = complete ? '' : '만 나이와 체중을 입력하면 비교할 수 있습니다.';
}

function invalidate() {
  updateProfileControls();
  saveSession();
  lastReport = null;
  $('#download').disabled = true;
  $('#scenarioConsent').checked = false;
  $('#result').textContent = '입력이 변경되었습니다. 가정을 확인하고 다시 계산하세요.';
}

function strengthLabel(value) {
  if (!value) return '정보 없음';
  return value.mg === null ? (value.raw || '함량 미확인') + ' (미확인)' : `${value.mg} mg`;
}

function comparisonTable(comparison, differencesOnly = false) {
  const rows = (comparison.rows || []).filter(r => !differencesOnly || r.status !== '일치');
  if (!rows.length) return '<p>대조할 성분 정보가 없습니다. 확인 필요.</p>';
  return '<div class="scroll"><table><thead><tr><th>성분</th><th>사진 추출</th><th>공식 함량</th><th>대조 상태</th></tr></thead><tbody>' + rows.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(strengthLabel(r.photo?.strength))}</td><td>${esc(strengthLabel(r.official?.strength))}</td><td><span class="match-state ${r.status === '일치' ? 'match-ok' : r.status === '함량 불일치' ? 'match-diff' : 'match-review'}">${esc(r.status)}</span></td></tr>`).join('') + '</tbody></table></div>';
}

function renderPhotoSummary(extracted, studio) {
  const x = extracted || {};
  const ingredients = Array.isArray(x.effective_ingredients) ? x.effective_ingredients : [];
  const cautions = Array.isArray(x.do_not_take_with) ? x.do_not_take_with.map(v => typeof v === 'string' ? v : v.item_name || '').filter(Boolean).join('\n') : '';
  const values = [
    ['제품명', x.product_name_raw], ['제조사', x.manufacturer],
    ['유효성분 목록', ingredients.map(i => `${i.ingredient_name || '성분명 미확인'} ${i.strength_per_unit || '(함량 미확인)'}`).join('\n')],
    ['성인 용법·용량', x.dosage_and_administration], ['하루 최대량 원문', x.max_daily_dose],
    ['중복·병용 관련 주의사항', cautions]
  ];
  const extractionTable = '<table><thead><tr><th>항목명</th><th>사진에서 읽은 내용</th></tr></thead><tbody>' + values.map(([name, value]) => `<tr><td>${esc(name)}</td><td>${esc(value || '사진에서 확인되지 않음').replace(/\n/g, '<br>')}</td></tr>`).join('') + '</tbody></table>';
  if (studio) {
    // 최종 출력은 재구성·요약·HTML 실행 없이 원문 문자열 그대로 표시합니다.
    $('#photoSummary').textContent = '';
    const output = document.createElement('pre');
    output.className = 'studio-final';
    output.textContent = typeof studio.final_text === 'string' && studio.final_text.length ? studio.final_text : 'Instruct 최종 결과를 받지 못했습니다. Extract로 대체하지 않습니다.';
    $('#photoSummary').appendChild(output);
    const evidence = document.createElement('details');
    evidence.innerHTML = '<summary>사진에서 읽은 상세 정보</summary>' + extractionTable;
    $('#photoSummary').appendChild(evidence);
  } else {
    $('#photoSummary').innerHTML = extractionTable;
  }
  const policy = studio ? `설정 ${studio.requested_config_id}번 고정 요청 / Instruct 원문 표시` : '가져온 Extract JSON';
  $('#analysisVersion').textContent = `${policy} / ${studio?.config_id ? '응답 설정 ' + studio.config_id : '응답에 설정 번호 없음'}${studio?.final_model ? ' / 최종 노드 ' + studio.final_model : ''}`;
}

async function renderCandidates(result) {
  candidates = result.candidates || [];
  photoId = result.photo_id;
  selected = null;
  $('#studioResult').textContent = JSON.stringify(result.studio || {extracted:result.photo_extracted}, null, 2);
  renderPhotoSummary(result.photo_extracted, result.studio);
  const name = result.studio ? result.search_name : result.photo_extracted?.product_name_raw;
  if (typeof name === 'string' && !searchName) searchName = name;
  if (result.studio && name) $('#searchReason').textContent = '인식한 제품명: ' + name;
  $('#searchReason').textContent = [result.studio && name ? '인식한 제품명: ' + name : '', result.reason, ...(result.warnings || []), ...(result.studio?.warnings || [])].filter(Boolean).join(' / ');
  renderProductOptions();
  if (candidates.length === 1 && Number(result.total ?? 1) === 1 && !result.requires_selection && result.search_mode !== 'similar') {
    $('#productPicker').hidden = true;
    $('#productPicker').open = false;
    await chooseProduct({target:{dataset:{productOption:'0'}}});
  } else if (candidates.length) {
    $('#productPicker').hidden = false;
    $('#productPicker').open = true;
    $('#basket').scrollIntoView({behavior:'smooth'});
    say(result.search_mode === 'similar' ? '비슷한 이름의 제품입니다. 사진과 제품명·함량·제형이 같은지 확인하고 선택하세요.' : '2번의 제품 선택 메뉴에서 맞는 제품명을 선택하세요.');
  } else {
    $('#productPicker').hidden = true;
    $('#productPicker').open = false;
    say('제품을 찾지 못했습니다. 제품명이 선명하게 보이도록 다시 촬영해 주세요.');
  }
}

function renderProductOptions() {
  $('#productOptions').innerHTML = candidates.map((c, index) => `<label class="product-option"><input type="radio" name="official-product" data-product-option="${index}" ${selected?.candidate_id === c.candidate_id ? 'checked' : ''}><span>${esc(c.product.ITEM_NAME || '제품명 미확인')}</span></label>`).join('') || '<p>조회된 제품이 없습니다.</p>';
}
let selectingProduct = false;
async function chooseProduct(event) {
  const indexText = event.target?.dataset?.productOption;
  if (indexText === undefined || selectingProduct) return;
  if (busy) {
    renderProductOptions();
    $('#selectionStatus').textContent = '현재 요청이 끝난 뒤 제품을 다시 선택하세요.';
    return;
  }
  const candidate = candidates[Number(indexText)];
  if (!candidate) return;
  selected = candidate;
  retryCandidateId = candidate.candidate_id;
  selectingProduct = true;
  $('#retrySelection').hidden = true;
  $('#productPicker').open = false;
  $('#selectionStatus').textContent = candidate.product.ITEM_NAME + ' — 공식 함량을 확인하고 있습니다.';
  try {
    await applySelected();
    $('#selectionStatus').textContent = basket.some(p => p.code === String(candidate.product.ITEM_SEQ))
      ? '선택한 제품이 아래 목록에 적용되었습니다. 수량 또는 확인이 필요한 항목을 입력하세요.' : '';
  } catch (error) {
    const message = '제품 적용 실패: ' + error.message + ' ' + recoveryHint(error.message);
    $('#selectionStatus').textContent = message;
    $('#retrySelection').hidden = false;
    say(message);
    selected = null;
    renderProductOptions();
  } finally { selectingProduct = false; }
}
// click also fires for an already checked radio, allowing retries without changing products.
$('#productOptions').onclick = chooseProduct;
$('#productOptions').onchange = chooseProduct;
$('#retrySelection').onclick = () => {
  const checkedIndex = candidates.findIndex(c => c.candidate_id === retryCandidateId);
  return chooseProduct({target:{dataset:{productOption:String(checkedIndex)}}});
};
let retryCandidateId = null;

let previewUrl = null;
let batchRunning = false;
let photoGroups = [];
let nextGroupId = 0;
function renderBatchQueue() {
  $('#batchChoices').innerHTML = photoGroups.map(group=>{
    const finished=group.status==='applied';
    return '<details class="photo-choice" '+(!finished?'open':'')+'><summary>'+'사진 '+group.id+' · '+esc(group.filename)+' · '+esc(finished?'목록에 추가됨':group.status==='error'?'분석 실패':group.status==='processing'?'처리 중':group.status==='empty'?'제품 미확인':'제품 선택 필요')+'</summary>'+
      (group.message?'<p>'+esc(group.message)+'</p>':'')+
      (!finished && group.result?.candidates?.length?'<div role="radiogroup" aria-label="'+esc(group.filename)+' 제품 선택">'+group.result.candidates.map((c,i)=>'<label class="product-option"><input type="radio" name="photo-group-'+group.id+'" data-photo-group="'+group.id+'" data-photo-option="'+i+'" '+(batchRunning || selectingProduct?'disabled':'')+'><span>'+esc(c.product.ITEM_NAME || '제품명 미확인')+'</span></label>').join('')+'</div>':'')+
      (group.status==='error' || group.status==='empty'?'<p class="muted">제품명이 선명한 사진을 다시 선택해 분석하세요. 다른 사진의 결과는 유지됩니다.</p>':'')+'</details>';
  }).join('');
}
async function choosePhotoGroup(event) {
  const id=event.target?.dataset?.photoGroup;
  const option=event.target?.dataset?.photoOption;
  if(id===undefined || option===undefined || batchRunning || busy || selectingProduct)return;
  const group=photoGroups.find(g=>g.id===Number(id));
  if(!group || group.status==='applied')return;
  const candidate=group.result.candidates[Number(option)];if(!candidate)return;
  candidates=group.result.candidates;photoId=group.result.photo_id;
  group.status='processing';renderBatchQueue();
  try {
    await chooseProduct({target:{dataset:{productOption:option}}});
    const added=basket.find(p=>p.code===String(candidate.product.ITEM_SEQ));
    group.status=added?'applied':'choice';
    group.message=added?(added.pending?'선택한 제품을 목록에 추가했습니다. 공식 함량은 확인이 필요합니다.':'선택한 제품을 목록에 추가했습니다. 수량을 입력하세요.'):'제품을 적용하지 못했습니다. 아래 오류 안내를 확인하고 다시 선택하세요.';
  } finally {renderBatchQueue();saveSession();}
}
$('#batchChoices').onclick=choosePhotoGroup;
$('#batchChoices').onchange=choosePhotoGroup;
$('#image').onchange = () => {
  if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=null;}
  $('#imagePreview').hidden=true;
  const files=Array.from($('#image').files || []);
  if(!files.length)return;
  if(files.length>20 || files.some(f=>!['image/jpeg','image/png','image/webp'].includes(f.type) || f.size>10*1024*1024)){
    $('#image').value='';say('장당 10MB 이하의 JPG·PNG·WEBP 사진을 최대 20장 선택해 주세요.');return;
  }
  previewUrl=URL.createObjectURL(files[0]);$('#previewImage').src=previewUrl;
  $('#previewCaption').textContent=files.length+'장 선택 · '+files.map(f=>f.name).join(', ');
  $('#imagePreview').hidden=false;
  say(files.length+'장의 사진을 선택했습니다. 각 사진을 독립적으로 분석합니다.');
};
async function analyzePhotoFiles(files,readPhoto) {
  if(batchRunning || busy || selectingProduct)throw Error('진행 중인 작업이 끝난 뒤 다시 시도하세요.');
  if(!files.length || files.length>20)throw Error('사진을 1~20장 선택하세요.');
  if(files.some(f=>!['image/jpeg','image/png','image/webp'].includes(f.type) || f.size>10*1024*1024))throw Error('사진은 장당 10MB 이하 JPG·PNG·WEBP만 지원합니다.');
  if(demoMode && basket.length)throw Error('예제 목록을 비운 뒤 실제 사진을 분석하세요.');
  batchRunning=true;$('#image').disabled=true;$('#jsonImport').disabled=true;updateProfileControls();
  const groups=files.map(file=>({id:++nextGroupId,filename:file.name,status:'processing',message:'분석 대기',result:null}));
  photoGroups.push(...groups);renderBatchQueue();
  $('#productPicker').hidden=true;$('#productPicker').open=false;
  try {
    for(let i=0;i<files.length;i++) {
      const group=groups[i],file=files[i];
      $('#batchProgress').textContent=(i+1)+' / '+files.length+'장 분석 중 · '+file.name;
      try {
        const base64=await readPhoto(file);
        const result=await api('/api/analyze-and-match',{base64,mime:file.type,consent:true});
        group.result=result;
        $('#studioResult').textContent=JSON.stringify(result.studio || {extracted:result.photo_extracted},null,2);
        renderPhotoSummary(result.photo_extracted,result.studio);
        $('#searchReason').textContent='최근 분석 사진: '+file.name+' · '+(result.search_name || result.photo_extracted?.product_name_raw || '제품명 미확인');
        const choices=result.candidates || [];
        if(choices.length===1 && Number(result.total ?? 1)===1 && !result.requires_selection && result.search_mode!=='similar') {
          candidates=choices;photoId=result.photo_id;
          await chooseProduct({target:{dataset:{productOption:'0'}}});
          const added=basket.find(p=>p.code===String(choices[0].product.ITEM_SEQ));
          group.status=added?'applied':'choice';
          group.message=added?(added.pending?'제품 선택 완료 · 공식 함량 확인 필요':'후보 1개를 자동 적용했습니다. 동일 제품은 중복 추가하지 않습니다.'):'적용 실패. 분석이 끝난 뒤 이 사진의 제품을 다시 선택하세요.';
        } else {
          group.status=choices.length?'choice':'empty';
          group.message=choices.length?(result.search_mode==='similar'?'비슷한 이름의 후보입니다. 사진과 제품명·제형·함량을 확인해 선택하세요.':'이 사진에 해당하는 제품 하나를 선택하세요.'):(result.reason || '공식 제품을 찾지 못했습니다.');
        }
      } catch(error) {group.status='error';group.message=(error.message || '분석 실패')+' '+recoveryHint(error.message || '');}
      renderBatchQueue();saveSession();
    }
  } finally {
    batchRunning=false;$('#image').disabled=false;$('#jsonImport').disabled=false;updateProfileControls();renderBatchQueue();saveSession();
    const remaining=groups.filter(g=>g.status==='choice').length;
    $('#batchProgress').textContent=files.length+'장 처리 완료 · 선택 대기 '+remaining+'장 · 실패/미확인 '+groups.filter(g=>['error','empty'].includes(g.status)).length+'장';
    $('#basket').scrollIntoView({behavior:'smooth'});
    say('사진 처리를 완료했습니다. 사진별 선택 항목과 제품 목록을 확인하세요.');
  }
}
$('#analyze').onclick = async () => {
  try {
    if(!$('#consent').checked)throw Error('사진 전송 동의란을 확인하세요.');
    await analyzePhotoFiles(Array.from($('#image').files || []),file=>new Promise((resolve,reject)=>{
      const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('사진 파일을 읽지 못했습니다.'));reader.readAsDataURL(file);
    }));
  } catch(error){showError(error);}
};

$('#jsonImport').onchange = async event => {
  try {
    if(batchRunning)throw Error('사진 분석이 끝난 뒤 가져오세요.');
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 1024 * 1024) throw Error('JSON은 1MB 이하로 입력하세요.');
    const imported = JSON.parse(await file.text());
    searchName = ''; page = 1;
    await renderCandidates(await api('/api/import-and-match', {extracted:imported.extracted || imported}));
  } catch (error) { showError(error); }
  event.target.value = '';
};

async function applySelected() {
  if (!selected) return;
  if (demoMode && basket.length) throw Error('가상 예제 목록을 초기화한 후 실제 제품을 추가하세요.');
  if (basket.some(p => p.code === String(selected.product.ITEM_SEQ))) {
    say('이미 적용된 제품입니다. 계산 목록에서 수량을 변경하세요.');
    return;
  }
  const support = null;
  const resolved = await api('/api/resolve-official', {candidate_id:selected.candidate_id});
  selected = {...selected,...resolved};
  if (!selected.comparison.calculation_ready) {
    basket.push({code:String(selected.product.ITEM_SEQ),name:selected.product.ITEM_NAME,
      ingredients:[],quantity:'0',quantity_unit:'',pending:true,support,candidate_id:selected.candidate_id,resolution:selected.resolution,
      comparison_status:'확인 필요',comparison_rows:selected.comparison.rows || [],
      comparison_warnings:selected.comparison.warnings || []});
    renderBasket();
    say('공식 자료 대조에서 확인이 필요합니다. 찾은 성분과 출처를 확인한 뒤 적용하세요.');
    openOverrideEditor(basket.length-1);
    await loadSelectedSupport(selected.candidate_id);
    return;
  }
  const result = await api('/api/auto-apply', {candidate_id:selected.candidate_id});
  basket.push({...result.product, approval_id:result.approval_id, support,candidate_id:selected.candidate_id});
  demoMode = false;
  renderBasket();
  say('선택한 제품을 공식 성분으로 적용했습니다. 가정 수량을 입력하세요.' + (result.comparison_status !== '일치' ? ' 사진 대조 결과는 확인 필요입니다.' : ''));
  $('#basket').scrollIntoView({behavior:'smooth'});
  await loadSelectedSupport(selected.candidate_id);
}

// Supplementary references must never prevent the selected product appearing.
async function loadSelectedSupport(candidateId) {
  try {
    const support = await api('/api/product-support', {candidate_id:candidateId});
    const product = basket.find(p => p.candidate_id === candidateId);
    if (product) { product.support = support; renderBasket(); }
  } catch { /* Optional information does not block product application. */ }
}

// Consolidate official wording without inventing advice or dropping dosage restrictions.
function cautionParagraph(item) {
  const parts = [];
  const seen = new Set();
  for (const field of ['useMethodQesitm','atpnWarnQesitm','atpnQesitm','intrcQesitm']) {
    if (typeof item?.[field] !== 'string') continue;
    const decoder = document.createElement('textarea');
    decoder.innerHTML = item[field].replace(/<[^>]*>/g, ' ');
    const plain = (decoder.value || decoder.textContent || item[field]).replace(/\s+/g, ' ').trim();
    for (const sentence of plain.split(/(?<=[.!?。])\s+/)) {
      const text = sentence.trim();
      if (text && !seen.has(text)) { seen.add(text); parts.push(text); }
    }
  }
  return parts.join(' ');
}
function supportHtml(support) {
  if (!support) return '';
  const easy = support.easy || {};
  const summary = cautionParagraph(easy.items?.[0]);
  return '<details><summary>주의사항</summary><p>' + esc(summary ||
    (easy.status === 'error' ? '주의사항을 불러오지 못했습니다. 제품 설명서를 확인하세요.' : '제공된 주의사항 정보가 없습니다. 제품 설명서를 확인하세요.')) + '</p></details>';
}

function pendingOfficialAmounts(product) {
  const proposal=product.pending && product.resolution?.proposal;
  if (!Array.isArray(proposal) || !proposal.length)return '';
  return '<div class="pending-official-amounts"><strong>공식 성분표에서 찾은 함량 · 계산 적용 전</strong>'+proposal.map(i=>'<p>'+esc(i.name)+' <b>'+esc(i.amount)+' '+esc(i.unit || 'mg')+'</b> / '+esc(i.basis_quantity)+esc(i.basis_unit)+'</p>').join('')+'<p>공식 API와 성분표 사이에 차이가 있어 계산에 자동 적용하지 않았습니다.</p><details><summary>공식 성분표와 충돌 이유 확인</summary><pre>'+esc((product.resolution.notes || []).join('\n'))+'\n'+esc(product.resolution.source_evidence || '')+'</pre></details>'+(product.resolution.source_url?'<a target="_blank" rel="noopener noreferrer" href="'+esc(product.resolution.source_url)+'">공식 제품 성분표 확인 ↗</a>':'')+'</div>';
}

function renderBasket() {
  invalidate();
  $('#basketCount').textContent = basket.length + '개';
  $('#basketHint').textContent = !basket.length ? '사진을 분석한 뒤 제품을 선택해 주세요.' : basket.some(p => p.pending) ? '함량 확인이 필요한 제품은 제외하거나 보완한 뒤 비교해 주세요.' : '0으로 입력한 약은 합산에서 제외됩니다. 액상약은 mL 단위로 입력하세요.';
  $('#basketList').className = basket.length ? '' : 'empty';
  $('#basketList').innerHTML = basket.map((p, n) => `<div class="basketitem"><div><strong>${esc(p.name)}</strong><small>${esc(p.code)} / ${p.pending ? '공식 함량 대조 중 · 계산 보류' : '공식 성분 ' + p.ingredients.length + '개'}${demoMode ? ' / 가상 예제' : ''}</small><p>${p.ingredients.map(i => esc(i.name) + ' ' + esc(i.amount) + ' ' + esc(i.unit || 'mg') + (i.measurement_basis === 'potency' ? '（역가）' : '') + ' / ' + esc(i.basis_quantity) + esc(i.basis_unit) + (i.equivalence ? ' · ' + esc(i.equivalence) : '')).join('<br>')}</p>${p.product_override ? '<details><summary>사용자 검토 보완 데이터 적용됨</summary><pre>' + esc(JSON.stringify(p.product_override,null,2)) + '</pre></details>' : ''}${p.automatic_resolution?.api_differences?.length ? '<p class="source-priority-note">공식 성분표 우선 적용 · API와 다른 함량·기준은 원문 근거로 보존했습니다.</p>' : ''}${supportHtml(p.support)}${pendingOfficialAmounts(p)}${p.pending ? '<p class="danger">공식 함량 확인 필요 · 계산 보류</p><details><summary>확인이 필요한 공식 데이터</summary>' + comparisonTable({rows:p.comparison_rows || []}) + (p.comparison_warnings || []).map(w => '<p>' + esc(w) + '</p>').join('') + '</details>' : ''}</div><label class="quantity-entry">비교할 수량 <input data-quantity="${n}" aria-label="${esc(p.name)} 가정 수량" type="number" min="0" max="1000000" step="any" value="${esc(p.quantity)}"> ${esc(p.quantity_unit || '개 (정·캡슐 등)')}</label><div class="product-actions">${p.restored_pending ? '<button data-recheck="' + n + '">공식 정보 다시 확인</button>' : ''}<button data-remove="${n}" aria-label="${esc(p.name)} 목록에서 제외">제외</button><details><summary>추가 관리</summary><button data-editor="${n}">함량 보완 · 검토자용</button></details></div></div>`).join('') || '<p>아직 추가한 약이 없습니다.</p><small>사진 분석 → 제품 선택 후 수량을 입력해 주세요.</small>';
  document.querySelectorAll('[data-recheck]').forEach(b => { b.onclick=async()=>{
    const product=basket[Number(b.dataset.recheck)];
    try {
      const result=await api('/api/recheck-product',{code:product.code});
      const index=basket.findIndex(p=>p===product);if(index<0)return;
      if(result.pending) {
        basket[index]={...product,restored_pending:false,pending:true,candidate_id:result.candidate_id,resolution:result.resolution,comparison_rows:result.comparison.rows,comparison_warnings:result.comparison.warnings};
      } else basket[index]={...result.product,approval_id:result.approval_id,quantity:product.quantity};
      renderBasket();say(result.pending?'공식 함량에 확인이 필요합니다. 추가 관리에서 근거를 확인하세요.':'공식 정보를 다시 확인했습니다. 수량을 유지했습니다.');
    } catch(error){showError(error);}
  }; });
  document.querySelectorAll('[data-editor]').forEach(b => { b.onclick = () => openOverrideEditor(Number(b.dataset.editor)); });
  document.querySelectorAll('[data-quantity]').forEach(i => { i.oninput = () => { basket[Number(i.dataset.quantity)].quantity = i.value; invalidate(); }; });
  document.querySelectorAll('[data-remove]').forEach(b => { b.onclick = () => { basket.splice(Number(b.dataset.remove),1); if (!basket.length) demoMode = false; renderBasket(); }; });
}
let editingProductCode = null;
function openOverrideEditor(index) {
  const p = basket[index];
  if (!p || !p.candidate_id) { say('사진을 다시 분석한 제품에서 등록하세요.'); return; }
  if (p.ingredients.some(i => i.unit === 'IU' || i.measurement_basis === 'potency')) {
    say('IU·역가 성분은 mg 수동 입력란에서 변경할 수 없습니다. 공식 자료를 다시 조회해 주세요.');
    return;
  }
  editingProductCode = p.code;
  const previous = p.product_override;
  const proposal = p.resolution;
  $('#overrideProduct').textContent = p.name + ' / 품목코드 ' + p.code + (proposal?.notes?.length ? ' / ' + proposal.notes.join(' / ') : '');
  $('#overrideIngredients').value = (previous?.ingredients || proposal?.proposal || p.ingredients).map(i => [i.name,i.ingredient_code || '',i.amount,i.basis_quantity,i.basis_unit].join('|')).join('\n');
  $('#overrideReviewer').value = previous?.reviewer || '';
  $('#overrideDate').value = previous?.reviewed_at || new Date().toLocaleDateString('sv-SE');
  $('#overrideSource').value = previous?.source_url || proposal?.source_url || '';
  $('#overrideEvidence').value = previous?.source_evidence || proposal?.source_evidence || '';
  $('#overrideReviewed').checked = false;
  $('#overrideEditor').hidden = false;
  $('#overrideEditor').open = true;
  $('#overrideEditor').scrollIntoView({behavior:'smooth'});
}
$('#overrideCancel').onclick = () => { $('#overrideEditor').hidden = true; editingProductCode = null; };
$('#overrideForm').onsubmit = async event => {
  event.preventDefault();
  try {
    const index = basket.findIndex(p => p.code === editingProductCode);
    if (index < 0) throw Error('등록할 제품을 다시 선택하세요.');
    const product = basket[index];
    const ingredients = $('#overrideIngredients').value.split(/\r?\n/).filter(line => line.trim()).map(line => {
      const fields = line.split('|').map(v => v.trim());
      if (fields.length !== 5) throw Error('각 성분 행에 성분명|코드|함량mg|기준수량|기준단위를 입력하세요.');
      return {name:fields[0],ingredient_code:fields[1],amount:fields[2],unit:'mg',basis_quantity:fields[3],basis_unit:fields[4]};
    });
    const result = await api('/api/register-product-override', {candidate_id:product.candidate_id,override:{ingredients,
      reviewer:$('#overrideReviewer').value,reviewed_at:$('#overrideDate').value,
      source_url:$('#overrideSource').value,source_evidence:$('#overrideEvidence').value,
      reviewed:$('#overrideReviewed').checked,complete:$('#overrideReviewed').checked}});
    // 요청 중 수량이 바뀌어도 사용자 입력을 유지합니다.
    const current = basket.findIndex(p => p.code === product.code);
    if (current < 0) { say('보완 데이터는 저장됐습니다. 제품이 목록에서 제거되어 화면에는 적용하지 않았습니다.'); return; }
    basket[current] = {...result.product,quantity:basket[current].quantity,approval_id:result.approval_id,
                       candidate_id:product.candidate_id,support:product.support};
    $('#overrideEditor').hidden = true;
    editingProductCode = null;
    renderBasket();
    say('품목별 보완 데이터를 mg 기준으로 저장하고 적용했습니다.');
  } catch (error) { showError(error); }
};

function updateIntentHelp() {
  const planned = $('#quantityIntent').value !== 'taken';
  $('#preventiveMission').hidden = !planned;
  $('#serviceTitle').textContent = planned ? '먹기 전, 여러 약의 위험 신호를 확인하세요.' : '이미 먹은 약의 성분과 양을 확인하세요.';
  $('#servicePurpose').textContent = planned
    ? '여러 약의 중복 성분과 용량 기준 초과, 공식 복용 주의사항을 확인해 사용자가 복용 전 위험 신호를 발견하도록 돕습니다.'
    : '입력한 복용량을 기준으로 중복 성분과 합산량을 확인합니다. 복용 시각·간격을 평가하거나 추가 복용 가능 여부를 판단하지 않습니다.';

  $('#intentHelp').textContent = $('#quantityIntent').value === 'taken'
    ? '입력한 복용량만 합산합니다. 복용 시각·간격은 평가하지 않으며 추가로 먹을 수 있는 양을 뜻하지 않습니다.'
    : '예정한 양만 비교합니다. 이미 먹은 양은 자동으로 더하지 않으며, 결과는 복용 허가가 아닙니다.';
}
$('#quantityIntent').onchange = () => { updateIntentHelp();invalidate(); };
$('#mode').onchange = invalidate;
$('#ageYears').oninput = invalidate;
$('#weightKg').oninput = invalidate;


$('#clear').onclick = () => {
  if(batchRunning || selectingProduct || busy){say('진행 중인 처리가 끝난 뒤 목록을 비워 주세요.');return;}
  basket=[];demoMode=false;photoGroups=[];renderBatchQueue();$('#batchProgress').textContent='';
  for(const id of ['ageYears','weightKg']) $('#'+id).value='';
  $('#errorHelp').hidden=true;
  $('#quantityIntent').value='planned';updateIntentHelp();
  renderBasket();
  try { if(typeof sessionStorage !== 'undefined')sessionStorage.removeItem(SESSION_KEY); } catch {}
  say('제품 목록과 입력 조건을 모두 지웠습니다.');
};
$('#demo').onclick = async () => { try { if(batchRunning)throw Error('사진 분석이 끝난 뒤 시도하세요.'); if (basket.length) throw Error('먼저 목록을 초기화하세요.'); basket = await (await fetch('/sample.json')).json(); demoMode = true; renderBasket(); } catch (error) { showError(error); } };
$('#evaluate').onclick = async () => {
  try {
    if(batchRunning)throw Error('모든 사진 분석이 끝난 뒤 비교하세요.');
    if (!profileIsComplete()) throw Error('만 나이와 체중을 올바르게 입력해 주세요.');
    if (basket.some(p => p.pending)) throw Error('공식 함량 확인이 필요한 제품이 있습니다. 해당 제품을 제외한 뒤 계산하세요.');
    if (!$('#scenarioConsent').checked) throw Error('가정 확인란을 선택하세요.');
    const data = demoMode ? {quantities:basket.map(p => p.quantity), mode:$('#mode').value} : {products:basket.map(p => ({approval_id:p.approval_id, quantity:p.quantity})), mode:$('#mode').value};
    data.quantity_intent = $('#quantityIntent').value;
    data.profile = {age_years:$('#ageYears').value || null,weight_kg:$('#weightKg').value || null};
    const report = await api(demoMode ? '/api/demo-evaluate' : '/api/evaluate', data);
    lastReport = report;
    $('#download').disabled = false;
    $('#result').className = '';
    renderComparisonResult(report);
    $('#resultStep').scrollIntoView({behavior:'smooth'});
    say('성분과 용량 기준 비교를 완료했습니다.');
  } catch (error) { showError(error); }
};
$('#download').onclick = () => {
  if (!lastReport) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastReport,null,2)],{type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = 'learningflow-revised-result.json'; a.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
};
// 뒤로 가기 캐시로 복원된 화면도 연결을 갱신하되 사진 재전송은 하지 않습니다.
if (typeof window !== 'undefined') window.addEventListener('pageshow', event => {
  if (event.persisted) start().then(restoreSession);
});
start().then(restoreSession);

function intakeReferenceHtml(report) {
  if (report.quantity_intent !== 'taken') return '';
  const ref=report.intake_reference;
  const warning='<p class="notice amber">이 비율은 섭취량과 등록 기준의 비교이며, 몸에 이상이 생길 확률이나 위험도 점수가 아닙니다. 낮아도 안전하거나 추가 복용이 가능하다는 뜻은 아닙니다. 복용 시각·간격과 개인 건강 상태는 반영하지 않습니다.</p>';
  if(!ref || ref.percent == null) return '<section class="intake-reference unknown"><h3>등록 기준 대비 섭취 비율</h3><strong>미판정 · 적용 가능한 기준 없음</strong><p>비교할 수 있는 기준이 없어 막대와 비율을 표시하지 않습니다. 하루 최대량 비교에는 ‘하루 총수량’ 모드와 해당 품목·나이·체중 조건이 필요합니다.</p>'+warning+'</section>';
  const value=Number(ref.percent);
  const rounded=Number.isFinite(value)?Number(value.toFixed(2)):0;
  const display=ref.criterion_status==='exceeded' && rounded<=100?'100% 초과':String(rounded)+'%';
  return `<section class="intake-reference ${ref.criterion_status==='exceeded'?'exceeded':'not_exceeded'}"><span class="result-kicker">이미 먹은 양 · 기준과의 비교</span><h3>등록 기준 대비 섭취 비율 <strong>${esc(display)}</strong></h3><p>대표 성분: <b>${esc(ref.ingredient)}</b> · 비교 가능한 성분 중 가장 높은 비율</p><div class="intake-meter"><progress max="200" value="${Math.min(200,Math.max(0,value))}" aria-label="${esc(ref.ingredient)} 기준 대비 섭취 비율" aria-valuetext="${esc(display)} · 위험도 점수 아님">${esc(display)}</progress><span class="limit-marker" aria-hidden="true"></span></div><div class="meter-labels" aria-hidden="true"><span>0%</span><span>100% · 등록 기준</span><span>200% 이상</span></div><p>섭취 합산량 <b>${esc(ref.total_mg)} mg</b> / 적용 기준 <b>${esc(ref.limit_mg)} mg${report.mode==='day'?'/일':''}</b>${ref.criterion_status==='exceeded'?' · 기준 초과량 <b>'+esc(ref.excess_mg)+' mg</b>':''}</p><p>${ref.criterion_status==='exceeded'?'등록 기준을 초과했습니다. 추가 복용을 결정하기 전에 약사·의료진에게 확인하세요.':'해당 성분의 등록 기준 미초과입니다. 다른 위험이나 추가 복용 가능 여부는 판정하지 않았습니다.'}</p><p class="coverage-note">기준 비교 ${esc(ref.comparable_count)}종 · 미판정 ${esc(ref.unknown_count)}종${ref.unknown_count?' — 미판정 성분은 대표 비율에 포함되지 않았습니다.':''}</p>${warning}</section>`;
}
function afterIntakeWarningsHtml(report) {
  if(report.quantity_intent !== 'taken')return '';
  return '<section class="official-dosage after-intake-warnings"><h3>복용 후 확인할 공식 주의사항·이상반응</h3><p>아래는 제품 허가 원문입니다. 현재 증상이 약 때문에 생겼는지 또는 앞으로 이상이 생길지를 판정한 결과가 아닙니다. 몸에 이상이 있거나 기준 초과가 확인됐다면 제품명·복용량·복용 시각을 정리해 의료진에게 확인하세요.</p>'+ (report.official_directions || []).map(p=>'<details><summary>'+esc(p.product_name)+'</summary><pre>'+esc(p.warnings_text || '공식 주의사항 원문을 받지 못했습니다. 제품 설명서를 확인하세요.')+'</pre>'+(p.source_url?'<a target="_blank" rel="noopener noreferrer" href="'+esc(p.source_url)+'">공식 제품 정보 확인 ↗</a>':'')+'</details>').join('')+'</section>';
}

function productLabelComparisonHtml(report) {
  const products=report.product_comparisons || [];
  if(!products.length)return '';
  return '<section id="productLabelResults" class="official-dosage product-label-comparison"><h3>제품별 공식 표시 용법 비교</h3><p>성분 합산 기준과 별도로, 각 제품의 입력 수량을 공식 1회량·횟수와 비교합니다. 아래 상한은 안전 복용량 추천이 아닙니다.</p>'+products.map(p=>{
    const labels={exceeded:'표시 용법 수량 초과',not_exceeded:'표시 용법 수량 미초과',age_restricted:'복용 금지 연령 해당',unknown:'용법 비교 미판정'};
    const style=p.status==='exceeded' || p.status==='age_restricted'?'exceeded':p.status==='not_exceeded'?'not_exceeded':'unknown';
    return '<article class="ingredient-result '+style+'"><div class="ingredient-title"><h4>'+esc(p.product_name)+'</h4><span class="criterion-badge">'+esc(labels[p.status] || labels.unknown)+'</span></div><p>입력: <b>'+esc(p.quantity)+' '+esc(p.unit)+'</b>'+(p.limit_quantity!=null?' / '+(report.mode==='day'?'하루':'1회')+' 표시 용법상 수량: <b>'+esc(p.limit_quantity)+' '+esc(p.unit)+'</b>':'')+'</p>'+(p.status==='exceeded'?'<p class="excess-amount">표시 용법 대비 초과량 '+esc(p.excess_quantity)+' '+esc(p.unit)+'</p>':'')+'<p>'+esc(p.note)+'</p>'+(p.matched_evidence?'<p class="muted">적용한 표의 행: '+esc(p.matched_evidence)+'</p>':'')+'<details><summary>판독에 사용한 공식 용법 원문</summary><pre>'+esc(p.source_text || '원문 없음')+'</pre></details>'+(p.source_url?'<a target="_blank" rel="noopener noreferrer" href="'+esc(p.source_url)+'">공식 제품 정보 ↗</a>':'')+'</article>';
  }).join('')+'</section>';
}

function detailedComparisonHtml(report) {
  const rows=report.ingredients || [];
  const over=rows.filter(i=>i.criterion_status==='exceeded');
  const within=rows.filter(i=>i.criterion_status==='not_exceeded');
  const unknown=rows.filter(i=>!['exceeded','not_exceeded'].includes(i.criterion_status));
  const planned = report.quantity_intent !== 'taken';
  const intentLabel=report.quantity_intent==='taken'?'이미 먹은 양':'앞으로 먹을 양';
  const period=report.mode==='day'?'하루 총량':'1회 비교량';
  const title=over.length?'등록된 용량 기준을 초과한 성분이 있습니다':unknown.length || !rows.length?'용량 기준을 확인할 수 없는 성분이 있습니다':'비교한 성분은 등록된 기준을 초과하지 않았습니다';
  const labels={exceeded:'기준 초과',not_exceeded:'기준 미초과'};
  const tone=over.length?'exceeded':unknown.length || !rows.length?'unknown':'not_exceeded';
  return `<div class="comparison-overview ${tone}"><span>${planned?'복용 전 위험 신호 확인':'입력한 복용량 사후 확인'} · ${esc(intentLabel)} · ${esc(period)}</span><h3>${esc(title)}</h3><div class="result-counts"><span>기준 초과 <b>${over.length}</b></span><span>기준 미초과 <b>${within.length}</b></span><span>미판정 <b>${unknown.length}</b></span></div><p>중복 성분 ${rows.filter(i=>i.duplicate).length}종 · 확인한 성분 ${rows.length}종</p></div><p class="notice amber">${esc(report.notice || '기준 미초과는 추가 복용 가능 또는 병용 안전을 의미하지 않습니다.')}</p>${productLabelComparisonHtml(report)}<h3 class="comparison-subtitle">제품 간 동일 성분 합산 비교</h3><p class="muted">아래 기준은 여러 제품의 성분을 합산한 양에 대한 비교입니다. 위 제품별 표시 용법 비교와 적용 범위가 다릅니다.</p><div class="ingredient-results">${[...over,...unknown,...within].map(i=>{
    const state=labels[i.criterion_status]?i.criterion_status:'unknown';
    const hasLimit=state!=='unknown' && i.limit_mg != null;
    const names=[...new Set((i.contributions || []).map(c=>c.product).filter(Boolean))];
    return `<article class="ingredient-result ${state}"><div class="ingredient-title"><h4>${esc(i.ingredient)}</h4><span class="criterion-badge">${esc(labels[state] || '미판정 · 기준 확인 필요')}</span></div><p>${i.duplicate?'동일 성분 중복 확인':'확인한 성분 중복 없음'}</p><div class="dose-comparison"><div><span>${esc(period)}</span><strong>${esc(i.total_amount ?? i.total_mg)} <small>${esc(i.total_unit || 'mg')}${i.measurement_basis==='potency'?' (역가)':''}</small></strong></div><span class="comparison-symbol" aria-hidden="true">${hasLimit?(state==='exceeded'?'>':'≤'):'—'}</span><div><span>적용 기준${hasLimit && report.mode==='day'?' / 일':''}</span><strong>${hasLimit?esc(i.limit_mg)+' <small>mg</small>':'<small>적용 가능한 기준 없음</small>'}</strong></div></div>${state==='exceeded' && i.excess_mg != null ? '<p class="excess-amount">기준 초과량 <strong>' + esc(i.excess_mg) + ' mg</strong></p><p class="muted">초과량은 기준과의 차이이며, 줄여 먹을 양이나 적정 복용량을 뜻하지 않습니다.</p>' : ''}<p>${state==='exceeded'?'입력한 합산량이 등록된 기준을 초과했습니다. 추가 복용 여부는 약사·의료진에게 확인하세요.':state==='not_exceeded'?'등록된 조건의 수치 기준 미초과입니다. 복용 가능 여부를 뜻하지 않습니다.':esc(i.criterion_note || '적용할 공식 합산 기준을 확인하지 못했습니다. 제품별 용법을 별도로 확인하세요.')}</p>${hasLimit?'<p class="criterion-scope">'+(i.criterion_scope==='ingredient'?'성분 공통 하루 기준 · 여러 제품 합산':'등록 품목 전용 기준')+'</p>':''}${names.length?'<p class="contributing-products">포함 제품: '+names.map(esc).join(' · ')+'</p>':''}${i.rule_source?'<a target="_blank" rel="noopener noreferrer" href="'+esc(i.rule_source)+'">적용한 공식 기준 확인 ↗</a>':''}</article>`;
  }).join('')}</div>${afterIntakeWarningsHtml(report)}${planned ? '<section class="official-dosage preventive-warnings"><h3>복용 전 공식 주의사항 확인</h3><p>병용 약·음식·음주 관련 주의사항이 포함될 수 있는 허가 원문입니다. 언급이 없거나 원문을 받지 못한 경우 병용 가능하다는 뜻이 아닙니다.</p>' + (report.official_directions || []).map(p => '<details><summary>' + esc(p.product_name) + '</summary><pre>' + esc(p.warnings_text || '공식 주의사항 원문을 받지 못했습니다. 제품 설명서와 약사·의료진에게 확인하세요.') + '</pre>' + (p.source_url ? '<a target="_blank" rel="noopener noreferrer" href="' + esc(p.source_url) + '">공식 제품 정보 확인 ↗</a>' : '') + '</details>').join('') + '</section>' : ''}<section class="official-dosage"><h3>제품별 공식 용법·용량</h3><p>허가 원문 전체입니다. 선택한 연령에 대한 맞춤 복용 지시가 아니며, 해당 연령·체중·복용 간격을 직접 확인해야 합니다.</p>${(report.official_directions || []).map(p=>`<details><summary>${esc(p.product_name)}</summary><pre>${esc(p.text || '공식 용법·용량 원문을 받지 못했습니다. 제품 설명서를 확인하세요.')}</pre>${p.source_url?'<a href="'+esc(p.source_url)+'" target="_blank" rel="noopener noreferrer">공식 제품 정보 확인 ↗</a>':''}</details>`).join('')}</section>`;
}

function renderComparisonResult(report) {
  const ingredients=report.ingredients || [], products=report.product_comparisons || [];
  const productOver=products.filter(p=>p.status==='exceeded');
  const ageRestricted=products.filter(p=>p.status==='age_restricted');
  const ingredientOver=ingredients.filter(i=>i.criterion_status==='exceeded');
  const duplicate=ingredients.filter(i=>i.duplicate);
  const unknown=ingredients.filter(i=>!['exceeded','not_exceeded'].includes(i.criterion_status));
  const productUnknown=products.filter(p=>p.status==='unknown');
  const hasOver=productOver.length || ingredientOver.length || ageRestricted.length;
  const hasUnknown=unknown.length || productUnknown.length || !ingredients.length;
  const taken=report.quantity_intent==='taken';
  const period=report.mode==='day'?'하루 총량':'1회 입력량';
  const title=ageRestricted.length?'복용 금지 연령에 해당하는 제품이 있습니다':hasOver?'등록된 기준을 초과한 항목이 있습니다':duplicate.length?'같은 성분이 겹칩니다. 주의사항을 확인하세요.':hasUnknown?'기준을 확인하지 못한 항목이 있습니다':'비교한 수치에서 등록 기준 초과는 확인되지 않았습니다';
  const tone=hasOver?'alert':hasUnknown || duplicate.length?'review':'neutral';
  const priorities=[];
  ageRestricted.forEach(p=>priorities.push({tag:'연령 제한',name:p.product_name,text:p.note || '공식 복용 금지 연령에 해당합니다.',tone:'alert'}));
  productOver.forEach(p=>priorities.push({tag:'제품별 표시 용법',name:p.product_name,text:'입력 '+p.quantity+' '+p.unit+' / '+(report.mode==='day'?'하루':'1회')+' 표시 수량 '+p.limit_quantity+' '+p.unit+' → 표시 용법 초과',tone:'alert'}));
  ingredientOver.forEach(i=>priorities.push({tag:'성분 합산 기준',name:i.ingredient,text:'합산 '+(i.total_amount ?? i.total_mg)+' '+(i.total_unit || 'mg')+' / 기준 '+i.limit_mg+' mg'+(report.mode==='day'?'/일':'')+(i.excess_mg!=null?' · 초과량 '+i.excess_mg+' mg':''),tone:'alert'}));
  duplicate.forEach(i=>priorities.push({tag:'중복 성분',name:i.ingredient,text:'여러 제품에 포함돼 있습니다. 중복 자체가 기준 초과를 뜻하지는 않습니다.',tone:'review'}));
  unknown.forEach(i=>priorities.push({tag:'합산 기준 미판정',name:i.ingredient,text:i.criterion_note || '적용 가능한 합산 기준이 없습니다.',tone:'review'}));
  productUnknown.forEach(p=>priorities.push({tag:'제품 용법 미판정',name:p.product_name,text:p.note || '공식 용법 조건을 확인하지 못했습니다.',tone:'review'}));
  const warnings=(report.official_directions || []);
  const warningHtml='<p class="muted">공식 허가 원문입니다. 모든 상호작용을 검사한 결과가 아니며, 원문이 없다고 주의사항이 없는 것은 아닙니다.</p>'+ (warnings.length?warnings.map(p=>'<details class="warning-product"><summary>'+esc(p.product_name)+'</summary><pre>'+esc(p.warnings_text || '공식 주의사항을 받지 못했습니다. 제품 설명서를 확인하세요.')+'</pre>'+(p.source_url?'<a href="'+esc(p.source_url)+'" target="_blank" rel="noopener noreferrer">공식 제품 정보 ↗</a>':'')+'</details>').join(''):'<p>공식 주의사항 원문을 받지 못했습니다. 제품 설명서를 확인하세요.</p>');
  $('#result').innerHTML=`<section class="simple-result ${tone}"><div class="result-eyebrow">${taken?'이미 먹은 양 · 사후 확인':'앞으로 먹을 양 · 복용 전 확인'}<span>${esc(period)}</span></div><h3>${esc(title)}</h3><div class="summary-metrics"><div><span>제품 용법 초과</span><strong>${productOver.length}<small>개</small></strong></div><div><span>성분 기준 초과</span><strong>${ingredientOver.length}<small>종</small></strong></div><div><span>중복 성분</span><strong>${duplicate.length}<small>종</small></strong></div><div><span>합산 미판정</span><strong>${unknown.length}<small>종</small></strong></div></div>${ageRestricted.length?'<p class="summary-restriction">복용 금지 연령 해당: '+ageRestricted.length+'개 제품</p>':''}<p class="summary-scope">제품 용법 미판정 ${productUnknown.length}개 · 확인 제품 ${products.length}개 / 성분 ${ingredients.length}종</p></section><p class="result-boundary">기준 미초과는 복용 가능을 뜻하지 않습니다. 복용 간격·개인 건강 상태·병용금기는 별도 확인이 필요합니다.</p><section class="priority-panel"><h3>가장 먼저 확인할 내용</h3>${priorities.length?'<div class="priority-list">'+priorities.slice(0,3).map((item,n)=>'<article class="priority-item '+item.tone+'"><span class="priority-order">'+(n+1)+'</span><div><span class="priority-tag">'+esc(item.tag)+'</span><h4>'+esc(item.name)+'</h4><p>'+esc(item.text)+'</p></div></article>').join('')+'</div>':'<p class="muted">등록된 수치 기준 초과는 확인되지 않았습니다. 공식 주의사항도 확인하세요.</p>'}${priorities.length>3?'<p class="more-results">추가 확인 항목 '+(priorities.length-3)+'개는 아래 상세 비교에서 볼 수 있습니다.</p>':''}</section>${taken?'<details class="result-disclosure"><summary>등록 기준 대비 섭취 비율 보기 <span>위험도 점수 아님</span></summary>'+intakeReferenceHtml(report)+'</details>':''}<details class="result-disclosure full-comparison"><summary>상세 비교 펼치기 <span>제품별 용법 · 전체 성분 · 초과량 · 공식 용법</span></summary><div class="detail-content">${detailedComparisonHtml(report)}</div></details><details class="result-disclosure official-warnings"><summary>공식 주의사항 펼치기 <span>${taken?'복용 후 주의사항·이상반응':'병용 약·음식·음주 관련 원문'}</span></summary><div class="detail-content">${warningHtml}</div></details>`;
}
