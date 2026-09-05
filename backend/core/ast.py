from pathlib import Path
import ast as pyast, re
LANG_EXT={'.py':'Python','.js':'JavaScript','.jsx':'JavaScript','.mjs':'JavaScript','.cjs':'JavaScript','.ts':'TypeScript','.tsx':'TypeScript','.go':'Go','.rs':'Rust','.java':'Java','.kt':'Kotlin','.kts':'Kotlin','.cs':'C#','.php':'PHP','.rb':'Ruby','.swift':'Swift','.dart':'Dart','.scala':'Scala'}
class ASTAnalyzer:
    def __init__(self,repo): self.repo=repo
    def analyze(self):
        files=[];imports=[];symbols=[];calls=[]
        for f in self.repo.files:
            lang=LANG_EXT.get(Path(f).suffix.lower())
            if not lang: continue
            text=self.repo.read(f); item={'file':f,'language':lang,'imports':[],'symbols':[],'calls':[],'parser':'stdlib-ast' if lang=='Python' else 'language-adapter'}
            if lang=='Python': self._python(text,item)
            elif lang in {'JavaScript','TypeScript'}: self._js(text,item)
            else: self._generic(text,item,lang)
            files.append(item); imports.extend({'from_file':f,**x} for x in item['imports']);symbols.extend({'file':f,**x} for x in item['symbols']);calls.extend({'file':f,**x} for x in item['calls'])
        return {'parser_framework':'adapter-v1','files':files[:5000],'imports':imports[:20000],'symbols':symbols[:20000],'calls':calls[:20000],'file_count':len(files),'note':'Non-Python adapters are syntax-aware lexical parsers; a Tree-sitter backend can be plugged in without changing the API.'}
    def _python(self,text,item):
        try: tree=pyast.parse(text)
        except SyntaxError:return
        for n in pyast.walk(tree):
            if isinstance(n,pyast.Import):
                for a in n.names:item['imports'].append({'module':a.name,'kind':'import','line':n.lineno})
            elif isinstance(n,pyast.ImportFrom):item['imports'].append({'module':n.module or '','kind':'from','line':n.lineno})
            elif isinstance(n,(pyast.FunctionDef,pyast.AsyncFunctionDef,pyast.ClassDef)):item['symbols'].append({'name':n.name,'kind':type(n).__name__,'line':n.lineno})
            elif isinstance(n,pyast.Call):
                fn=getattr(n.func,'id',None) or getattr(n.func,'attr',None)
                if fn:item['calls'].append({'name':fn,'line':n.lineno})
    def _js(self,text,item):
        for m in re.finditer(r'^\s*import\s+(?:.+?\s+from\s+)?[\'\"]([^\'\"]+)',text,re.M):item['imports'].append({'module':m.group(1),'kind':'import','line':text.count('\n',0,m.start())+1})
        for m in re.finditer(r'^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+(\w+)',text,re.M):item['symbols'].append({'name':m.group(1),'kind':'declaration','line':text.count('\n',0,m.start())+1})
        for m in re.finditer(r'\b(?:require|fetch|axios|express|Router|createServer)\s*\(',text):item['calls'].append({'name':m.group(0).split('(')[0].strip(),'line':text.count('\n',0,m.start())+1})
    def _generic(self,text,item,lang):
        for pat in [r'^(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*[\w<>\[\], ?]+\s+(\w+)\s*\([^;]*\)\s*\{',r'^\s*(?:fn|func|function)\s+(\w+)']:
            for m in re.finditer(pat,text,re.M):item['symbols'].append({'name':m.group(1),'kind':'declaration','line':text.count('\n',0,m.start())+1})
        pats={'Go':r'^\s*import\s+\(?\s*[\"`]([^\"`]+)','Rust':r'^\s*(?:use|extern crate)\s+([^;:]+)','Java':r'^\s*import\s+([^;]+)','Kotlin':r'^\s*import\s+([^\s]+)','C#':r'^\s*using\s+([^;]+)','PHP':r'^\s*(?:use|require|include)\s+[\"\']?([^\"\';]+)','Ruby':r'^\s*(?:require|require_relative)\s+[\"\']([^\"\']+)', 'Swift':r'^\s*import\s+(\w+)','Dart':r'^\s*import\s+[\"\']([^\"\']+)', 'Scala':r'^\s*import\s+([^\s]+)'}
        pat=pats.get(lang)
        if pat:
            for m in re.finditer(pat,text,re.M):item['imports'].append({'module':m.group(1).strip(),'kind':'import','line':text.count('\n',0,m.start())+1})
