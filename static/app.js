const state = { candidates: [], recommendations: [] };
const $ = (id) => document.getElementById(id);
const sample = "招聘材料方向博士，研究固态电解质或锂离子电池正极材料，熟悉 XRD、SEM、电化学测试，有 SCI 论文，适合新能源研发岗位。";

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
  renderCandidateTable(state.candidates);
}

function renderCandidateTable(candidates) {
  $("candidateTable").innerHTML = candidates.map(c => `<tr>
    <td><strong>${c.resume_id}</strong><span>${c.graduation_year} 届</span></td>
    <td><strong>${c.degree} · ${c.school}</strong><span>${c.major}</span></td>
    <td>${c.research_directions.join(" / ")}</td>
    <td>${c.experimental_skills.slice(0,4).join(" / ")}</td>
    <td><strong>SCI ${c.paper_count} 篇</strong><span>专利 ${c.patent_count} 项</span></td>
    <td>${c.industry_tags.join(" / ")}</td>
  </tr>`).join("");
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
Promise.all([loadHealth(), loadCandidates()]).catch(() => toast("初始化失败，请确认服务已启动"));

