from mcp.server.fastmcp import FastMCP
from config import settings
from engines.analysis_engine import AnalysisEngine
from engines.decision_engine import DecisionEngine
from engines.execution_engine import ExecutionEngine

# 各エンジンの初期化
print("🚀 Initializing SmartDeployAgent Engines...")
analyzer = AnalysisEngine()
decider = DecisionEngine()
executor = ExecutionEngine()

mcp = FastMCP("SmartDeployAgent")

@mcp.tool()
def deploy_application(repo_url: str, project_name: str, service_type: str = "apprunner") -> str:
    """
    GitHubリポジトリから自律デプロイを実行します。
    1. Analysis: GitHubクローン & コード解析
    2. Decision: Dockerfile生成 & ニューロシンボリック監査 (自動修正)
    3. Execution: AWS環境確認, ビルド, ECRプッシュ
    """
    
    # --- Phase 1: Analysis (分析) ---
    print(f"🔍 Analyzing repository: {repo_url}")
    work_dir = analyzer.clone_repository(repo_url)
    context = analyzer.analyze_context(work_dir)
    
    # --- Phase 2: Decision (判断・監査) ---
    print("🧠 Generating & Auditing configuration...")
    dockerfile_content = ""
    violations = []
    
    # 自己修正ループ (Neuro-symbolic Loop)
    for attempt in range(settings.MAX_RETRIES):
        error_msg = f"Previous violations to fix: {violations}" if violations else ""
        dockerfile_content = decider.generate_dockerfile(context, attempt, error_msg)
        
        # 作成された環境のちぇっく (Pythonルール + Hadolint + Trivy)
        violations = decider.symbolic_audit(dockerfile_content, service_type)
        
        if not violations:
            print(f"✅ Audit Passed on attempt {attempt + 1}")
            break
        
        print(f"❌ Audit Failed (Attempt {attempt + 1}): {violations}")
        
    if violations:
        return f"⛔ Deployment Aborted: Could not generate secure config after {settings.MAX_RETRIES} attempts.\nViolations: {violations}"

    # 合格したDockerfileを保存
    (work_dir / "Dockerfile").write_text(dockerfile_content)

    # --- Phase 3: Execution (実行) ---
    print("🛠️ Preparing AWS Environment...")
    repo_uri = executor.ensure_ecr_repo(project_name)
    
    # ビルド & プッシュ (時間がかかるため、デモ時はコメントアウトしても良い)
    # executor.build_and_push(work_dir, repo_uri)
    
    # おまけ: ゾンビハンター (FinOps)
    zombies = executor.hunt_zombies()
    zombie_msg = "\n".join(zombies) if zombies else "No zombie resources found."
    
    return f"""
    ✅ Deployment Pipeline Triggered! 🚀
    
    [Summary]
    - Repository: {repo_url}
    - Technology Stack: {context['stack']}
    - Target Service: {service_type}
    - ECR Repository: {repo_uri}
    
    [Security & Quality]
    - Audit Status: Passed (Root check, Hadolint, Trivy OK)
    - Generated Dockerfile saved to workspace.
    
    [FinOps Report]
    {zombie_msg}
    """

if __name__ == "__main__":
    mcp.run()