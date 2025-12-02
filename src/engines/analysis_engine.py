import shutil
from pathlib import Path
from git import Repo
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from config import settings

class AnalysisEngine:
    def __init__(self):
        self._initialize_bedrock()
        self.rules_index = self._load_rules_index()

    def _initialize_bedrock(self):
        """Bedrockの設定 (rag_loader.py の initialize_llama_index_settings 相当)"""
        Settings.llm = Bedrock(
            model=settings.LLM_MODEL_ID,
            region_name=settings.AWS_REGION
        )
        Settings.embed_model = BedrockEmbedding(
            model_name=settings.EMBED_MODEL_ID,
            region_name=settings.AWS_REGION
        )

    def _load_rules_index(self):
        """社内規定(security_rules)を読み込んでインデックス化"""
        if not settings.RULES_DIR.exists():
            print("⚠️ Security rules directory not found. Skipping rule indexing.")
            return None
        
        # Markdownファイルなどを読み込む
        documents = SimpleDirectoryReader(
            str(settings.RULES_DIR),
            recursive=True
        ).load_data()
        
        if not documents:
            return None

        print(f"🔒 Loaded {len(documents)} security rule documents.")
        return VectorStoreIndex.from_documents(documents)

    def clone_repository(self, repo_url: str) -> Path:
        """Git Cloneを実行し、作業ディレクトリを返す"""
        if settings.WORK_DIR.exists():
            shutil.rmtree(settings.WORK_DIR)
        settings.WORK_DIR.mkdir(parents=True, exist_ok=True)
        
        print(f"📥 Cloning {repo_url}...")
        Repo.clone_from(repo_url, settings.WORK_DIR)
        return settings.WORK_DIR

    def analyze_context(self, project_path: Path) -> dict:
        """
        コードをRAG解析し、技術スタックと適用すべきルールを抽出する
        """
        # 1. git clone & コードのインデックス化
        print("🧠 Analyzing source code...")
        code_documents = SimpleDirectoryReader(
            input_dir=str(project_path),
            recursive=True,
            exclude=["*.git*", "*.lock", "node_modules", "__pycache__"]
        ).load_data()
        
        code_index = VectorStoreIndex.from_documents(code_documents)
        code_query_engine = code_index.as_query_engine()

        # 2. コードの分析
        tech_stack_info = str(code_query_engine.query(
            "Identify the programming language, framework, and the entry point command (e.g., 'python app.py' or 'npm start') of this project. "
            "Also list key dependencies."
        ))
        print(f"🧐 Detected Stack: {tech_stack_info}")

        # 3. ルール検索 (技術スタックに基づいて検索)
        security_context = "No specific rules found. Follow standard best practices."
        if self.rules_index:
            rules_retriever = self.rules_index.as_retriever(similarity_top_k=3)
            
            # AIが特定したスタック名を使って、関連するルールを検索
            nodes = rules_retriever.retrieve(f"security requirements for {tech_stack_info} dockerfile")
            security_context = "\n".join([n.get_content() for n in nodes])

        return {
            "stack_summary": tech_stack_info,
            "security_context": security_context,
            # 生成AIに渡すためのファイルツリー情報も一応残しておく
            "file_tree": [f.name for f in project_path.iterdir()]
        }