const state = { candidates: [], recommendations: [], importPoller: null };
const $ = (id) => document.getElementById(id);
const sample = "招聘材料方向博士，研究固态电解质或锂离子电池正极材料，熟悉 XRD、SEM、电化学测试，有 SCI 论文，适合新能源研发岗位。";
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 2200);
}

async function loadHealth() {
  const data = await fetch("/api/health").then(r => r.json());
  $("candidateCount").textContent = data.candidate_count;
  $("modelStatus").textContent = data.llm_configured ? `${data.model} 已连接` : "本地规则模式";
}

async function loadCandidates() {
  state.candidates = await fetch("/api/candidates").then(r => r.json());
  $("candidateCount").textContent = state.candidates.length;
  renderCandidateTable(state.candidates);
}

function renderCandidateTable(candidates) {
  $("candidateTable").innerHTML = candidates.map(c => `<tr class="library-candidate-row" data-id="${esc(c.resume_id)}" tabindex="0">
    <td><strong>${esc(c.resume_id)}</strong><span>${esc(c.graduation_year)} 届</span></td>
    <td><strong>${esc(c.degree)} · ${esc(c.school)}</strong><span>${esc(c.major)}</span></td>
    <td>${esc(c.research_directions.join(" / "))}</td>
    <td>${esc(c.experimental_skills.slice(0,4).join(" / "))}</td>
    <td><strong>SCI ${c.paper_count} 篇</strong><span>专利 ${c.patent_count} 项</span></td>
    <td>${esc(c.industry_tags.join(" / "))}</td>
  </tr>`).join("");
  document.querySelectorAll(".library-candidate-row").forEach(row => {
    row.addEventListener("click", () => openLibraryCandidate(row.dataset.id));
    row.addEventListener("keydown", event => { if (event.key === "Enter") openLibraryCandidate(row.dataset.id); });
  });
}

function listBlock(title, items) {
  const values = (items || []).filter(Boolean);
  return `<div class="detail-section"><h3>${title}</h3>${values.length ? `<ul>${values.map(item=>`<li>${esc(item)}</li>`).join("")}</ul>` : `<p>未识别到相关信息</p>`}</div>`;
}

function openLibraryCandidate(id) {
  const c = state.candidates.find(candidate => candidate.resume_id === id);
  if (!c) return;
  const research = (c.research_experience || []).map(item => `<div class="structured-record"><strong>${esc(item.title || "科研经历")}</strong><p>${esc(item.summary)}</p><div class="tag-row">${(item.content_tags || []).map(tag=>`<span class="tag">${esc(tag)}</span>`).join("")}</div>${(item.paper_outputs || []).length ? `<small>成果：${esc(item.paper_outputs.join("；"))}</small>` : ""}</div>`).join("");
  const careers = (c.work_experience || []).map(item => `<div class="structured-record"><strong>${esc(item.organization || "实习 / 工作经历")} ${esc(item.role)}</strong><p>${esc(item.period)} ${esc(item.summary)}</p><div class="tag-row">${(item.content_tags || []).map(tag=>`<span class="tag">${esc(tag)}</span>`).join("")}</div></div>`).join("");
  $("dialogContent").innerHTML = `<div class="dialog-head"><span class="badge">结构化人才档案</span><h2>${esc(c.resume_id)} · ${esc(c.school)}</h2><p>${esc(c.degree)} · ${esc(c.major)} · ${esc(c.graduation_year)} 届</p></div>
    <div class="dialog-body">
      <div class="detail-section"><h3>大模型整体概括</h3><p>${esc(c.resume_summary || "暂无整体概括")}</p></div>
      <div class="structured-overview"><div><span>绩点排名</span><strong>${esc(c.gpa_ranking || "未识别")}</strong></div><div><span>英语水平</span><strong>${esc(c.english_level || "未识别")}</strong></div><div><span>研究方向</span><strong>${esc((c.research_directions || []).join(" / "))}</strong></div><div><span>技能认证</span><strong>${esc((c.skill_certifications || []).join(" / ") || "未识别")}</strong></div></div>
      <div class="detail-section"><h3>科研经历、论文成果及内容标签</h3>${research || "<p>未识别到相关信息</p>"}</div>
      <div class="detail-section"><h3>实习 / 工作经历</h3>${careers || "<p>未识别到相关信息</p>"}</div>
      ${listBlock("竞赛获奖", c.competition_awards)}
      ${listBlock("学生工作", c.student_work)}
      <div class="detail-section"><h3>自我评价口袋</h3><p>${esc(c.self_evaluation || "未识别到无法归入其他模块的信息")}</p></div>
    </div>`;
  $("candidateDialog").showModal();
}

function updateFileSelection(files) {
  const count = files?.length || 0;
  $("fileSelection").textContent = count ? `已选择 ${count} 个文件，提交后将在后台统一处理` : "单文件上限 1GB；图片 OCR 需安装 Tesseract";
}

async function startImport() {
  const files = $("resumeFiles").files;
  if (!files.length) return toast("请选择简历文件或 ZIP 压缩包");
  const button = $("startImportButton");
  button.disabled = true; button.textContent = "正在流式上传...";
  try {
    let payload;
    for (const file of [...files]) payload = await uploadFileInChunks(file, $("importUseLlm").checked, button);
    $("resumeFiles").value = ""; updateFileSelection();
    toast(`导入任务 ${payload.job_id} 已创建`);
    await loadImportJobs();
    beginImportPolling();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "创建导入任务"; }
}

async function uploadFileInChunks(file, useLlm, button) {
  let response = await fetch("/api/upload-sessions", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({file_name:file.name,file_size:file.size,use_llm:useLlm})
  });
  let session = await response.json();
  if (!response.ok) throw new Error(session.detail || "创建上传会话失败");
  let chunkIndex = 0;
  for (let start = 0; start < file.size; start += session.chunk_size) {
    const end = Math.min(start + session.chunk_size, file.size);
    button.textContent = `上传 ${file.name} · ${Math.round(end / file.size * 100)}%`;
    response = await fetch(`/api/upload-sessions/${session.upload_id}/chunks/${chunkIndex}`, {
      method:"PUT", body:file.slice(start, end)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "分块上传失败");
    chunkIndex += 1;
  }
  response = await fetch(`/api/upload-sessions/${session.upload_id}/complete`, {method:"POST"});
  const job = await response.json();
  if (!response.ok) throw new Error(job.detail || "创建解析任务失败");
  return job;
}

async function loadImportJobs() {
  const jobs = await fetch("/api/import-jobs?limit=8").then(r => r.json());
  $("importJobs").innerHTML = jobs.length ? jobs.map(job => {
    const percent = job.total ? Math.round(job.processed / job.total * 100) : 0;
    const status = {queued:"等待处理",processing:"结构化解析中",completed:"已完成",failed:"失败"}[job.status] || job.status;
    return `<div class="import-job"><div><strong>${esc(job.job_id)}</strong><span>${status}</span></div>
      <div><div class="progress-track"><div class="progress-fill" style="width:${percent}%"></div></div><span>${job.processed} / ${job.total} · ${percent}%</span></div>
      <div class="job-metrics">成功 ${job.succeeded} · 失败 ${job.failed}<br>LLM ${job.llm_parsed}</div>
      ${(job.errors || []).length || (job.skipped || []).length ? `<details class="job-errors"><summary>查看异常与跳过文件</summary>${[...(job.errors || []),...(job.skipped || [])].slice(0,20).map(item=>`<p><b>${esc(item.file)}</b>：${esc(item.message)}</p>`).join("")}${["completed","failed"].includes(job.status) ? `<button class="secondary-button retry-job" data-job-id="${esc(job.job_id)}">重试解析</button>` : ""}</details>` : ""}</div>`;
  }).join("") : "";
  document.querySelectorAll(".retry-job").forEach(button => button.addEventListener("click", async event => {
    event.preventDefault();
    const response = await fetch(`/api/import-jobs/${button.dataset.jobId}/retry`, {method:"POST"});
    const result = await response.json();
    if (!response.ok) return toast(result.detail || "重试失败");
    toast(`任务 ${result.job_id} 已重新开始`);
    beginImportPolling();
    loadImportJobs();
  }));
  if (jobs.some(job => ["queued","processing"].includes(job.status))) beginImportPolling();
  else if (state.importPoller) { clearInterval(state.importPoller); state.importPoller = null; await loadCandidates(); }
}

function beginImportPolling() {
  if (!state.importPoller) state.importPoller = setInterval(() => loadImportJobs().catch(()=>{}), 1500);
}

function renderProfile(profile) {
  const items = [
    ["学历要求", profile.degree_requirement || "未指定"],
    ["研究方向", profile.research_directions.join(" / ") || "开放方向"],
    ["核心技能", profile.required_skills.join(" / ") || "未指定"],
    ["优先成果", profile.preferred_outputs.join(" / ") || "综合评估"],
    ["产业方向", profile.industry_direction || "材料研发"],
  ];
  $("profileGrid").innerHTML = items.map(([label, value]) => `<div class="profile-item"><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function renderPipeline(pipeline) {
  $("pipelineStrip").innerHTML = pipeline.map(step => `<div class="pipeline-step"><b>${step.count}</b><div><strong>${step.name}</strong><span>${step.detail}</span></div></div>`).join("");
}

function renderRecommendations(items) {
  state.recommendations = items;
  $("recommendations").innerHTML = items.map(item => `<article class="candidate-card" data-id="${item.candidate.resume_id}" tabindex="0">
    <div class="rank-score"><b>${item.score}</b><span>匹配分 · #${item.rank}</span></div>
    <div class="candidate-main"><h3>${item.candidate.resume_id} <span class="badge">${item.candidate.degree}</span></h3><p>${item.candidate.school} · ${item.candidate.major}</p><div class="tag-row">${item.candidate.research_directions.slice(0,3).map(t=>`<span class="tag">${t}</span>`).join("")}</div></div>
    <div class="candidate-reason">${item.reasons.slice(0,3).map(r=>`<p>${r}</p>`).join("")}</div>
    <div class="candidate-action"><strong>${item.recommendation_level}</strong><span>查看完整依据 →</span></div>
  </article>`).join("");
  document.querySelectorAll(".candidate-card").forEach(card => {
    card.addEventListener("click", () => openCandidate(card.dataset.id));
    card.addEventListener("keydown", event => { if (event.key === "Enter") openCandidate(card.dataset.id); });
  });
}

function openCandidate(id) {
  const item = state.recommendations.find(r => r.candidate.resume_id === id);
  if (!item) return;
  const b = item.breakdown;
  const bars = [["研究方向",b.research,25],["技能",b.skills,25],["学历",b.education,15],["科研成果",b.outputs,20],["产业适配",b.industry,15]];
  $("dialogContent").innerHTML = `<div class="dialog-head"><span class="badge">${item.recommendation_level}</span><h2>${item.candidate.resume_id} · ${item.score} 分</h2><p>${item.candidate.school} · ${item.candidate.degree} · ${item.candidate.major} · ${item.candidate.graduation_year} 届</p></div>
    <div class="dialog-body"><div class="detail-section"><h3>五维评分</h3><div class="score-bars">${bars.map(([n,v,m])=>`<div class="bar"><span>${n}</span><div class="bar-track"><div class="bar-fill" style="width:${v/m*100}%"></div></div><b>${v}</b></div>`).join("")}</div></div>
    <div class="detail-section"><h3>推荐理由</h3><ul>${item.reasons.map(x=>`<li>${x}</li>`).join("")}</ul></div>
    <div class="detail-section"><h3>简历证据</h3><ul>${item.evidence.map(x=>`<li>${x}</li>`).join("")}</ul></div>
    <div class="detail-section"><h3>潜在不足</h3><ul>${item.weaknesses.map(x=>`<li>${x}</li>`).join("")}</ul></div>
    <div class="detail-section"><h3>项目经历</h3><p>${item.candidate.project_experience}</p><p>${item.candidate.internship_experience || "未明确体现企业实习经历。"}</p></div></div>`;
  $("candidateDialog").showModal();
}

async function runRecommendation() {
  const query = $("queryInput").value.trim();
  if (query.length < 4) return toast("请先输入完整的岗位需求");
  const button = $("recommendButton");
  button.disabled = true; button.innerHTML = "<span>⌁</span>推荐流程运行中...";
  try {
    const response = await fetch("/api/recommend", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
      query, top_k:Number($("topK").value), strict_degree:$("strictDegree").checked, use_llm:$("useLlm").checked
    })});
    if (!response.ok) throw new Error((await response.json()).detail || "请求失败");
    const data = await response.json();
    renderProfile(data.job_profile); renderPipeline(data.pipeline); renderRecommendations(data.recommendations);
    $("elapsedBadge").textContent = `${data.elapsed_ms} ms`;
    $("llmBadge").textContent = data.llm_used ? `${data.model} 已参与精排` : "本地可解释规则";
    $("resultCount").textContent = `已输出 ${data.recommendations.length} 位候选人`;
    $("emptyState").classList.add("hidden"); $("resultsArea").classList.remove("hidden");
    toast(`推荐完成，共输出 ${data.recommendations.length} 位候选人`);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = "<span>⌕</span>开始推荐"; }
}

document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item,.view").forEach(el => el.classList.remove("active"));
  button.classList.add("active"); $(`${button.dataset.view}View`).classList.add("active");
  $("viewTitle").textContent = button.textContent.trim();
}));
$("sampleButton").addEventListener("click", () => { $("queryInput").value = sample; $("queryInput").focus(); });
$("recommendButton").addEventListener("click", runRecommendation);
$("closeDialog").addEventListener("click", () => $("candidateDialog").close());
$("candidateSearch").addEventListener("input", event => {
  const q = event.target.value.toLowerCase();
  renderCandidateTable(state.candidates.filter(c => JSON.stringify(c).toLowerCase().includes(q)));
});
$("openImportButton").addEventListener("click", () => { $("importPanel").classList.remove("hidden"); loadImportJobs(); });
$("cancelImportButton").addEventListener("click", () => $("importPanel").classList.add("hidden"));
$("resumeFiles").addEventListener("change", event => updateFileSelection(event.target.files));
$("startImportButton").addEventListener("click", startImport);
["dragenter","dragover"].forEach(name => $("dropZone").addEventListener(name, event => { event.preventDefault(); $("dropZone").classList.add("dragging"); }));
["dragleave","drop"].forEach(name => $("dropZone").addEventListener(name, event => { event.preventDefault(); $("dropZone").classList.remove("dragging"); }));
$("dropZone").addEventListener("drop", event => { $("resumeFiles").files = event.dataTransfer.files; updateFileSelection(event.dataTransfer.files); });
Promise.all([loadHealth(), loadCandidates(), loadImportJobs()]).catch(() => toast("初始化失败，请确认服务已启动"));
