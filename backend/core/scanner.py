from pathlib import Path
import hashlib, json

IGNORE = {'.git','node_modules','vendor','.venv','venv','__pycache__','.next','dist','build','target','.terraform','.gradle','.idea','.vscode','coverage','bin','obj','.pytest_cache','.mypy_cache','.tox','.cache','.pnpm-store','.yarn'}
TEXT_EXT = {'.js','.jsx','.ts','.tsx','.mjs','.cjs','.py','.go','.rs','.java','.kt','.kts','.cs','.php','.rb','.swift','.dart','.scala','.sh','.bash','.md','.json','.yaml','.yml','.toml','.xml','.gradle','.properties','.env','.ini','.conf','.tf','.tfvars','.sql','.lock'}
MAX_FILE_BYTES = 2_000_000
MAX_TEXT_BYTES = 250_000

class Repository:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.files = self._files()
        self.file_set = set(self.files)
        self.text = {}
        for f in self.files:
            p = Path(f)
            if p.suffix.lower() in TEXT_EXT or p.name.lower() in {'dockerfile','makefile','gemfile','procfile'}:
                self.text[f] = self.read(f)
        self.corpus = '\n'.join(f'--- {k} ---\n{v}' for k,v in self.text.items())
        self.lower = self.corpus.lower()
    def _files(self):
        out=[]
        for p in self.root.rglob('*'):
            try:
                rel=p.relative_to(self.root)
                if p.is_file() and p.stat().st_size <= MAX_FILE_BYTES and not any(part in IGNORE for part in rel.parts): out.append(rel.as_posix())
            except OSError: continue
        return sorted(out)
    def read(self, rel, limit=MAX_TEXT_BYTES):
        try:
            p=self.root/rel
            if p.stat().st_size > MAX_FILE_BYTES: return ''
            return p.read_text(errors='ignore')[:limit]
        except Exception: return ''
    def json(self, rel):
        try: return json.loads(self.read(rel))
        except Exception: return {}
    def exists(self,*names): return any(n in self.file_set for n in names)
    def files_matching(self,prefix): return [f for f in self.files if f.startswith(prefix)]
    def hash(self):
        h=hashlib.sha256()
        for f in self.files: h.update(f.encode()); h.update(self.read(f,10000).encode(errors='ignore'))
        return h.hexdigest()
    def size_bytes(self):
        total=0
        for f in self.files:
            try: total += (self.root/f).stat().st_size
            except OSError: pass
        return total
