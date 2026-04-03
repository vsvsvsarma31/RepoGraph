
from __future__ import annotations
import ast, dataclasses, hashlib, html, itertools, json, math, os, subprocess, sys, tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
try:
    from tree_sitter_languages import get_parser as get_ts_parser  # type: ignore
except Exception:
    get_ts_parser = None  # type: ignore
SKIP_DIRS={'.git','node_modules','dist','build','__pycache__'}
LANG_BY_EXT={'.py':'python','.js':'javascript','.jsx':'javascript','.ts':'typescript','.tsx':'typescript','.go':'go','.rs':'rust','.java':'java'}
TEXT_EXTS=set(LANG_BY_EXT)
NODE_PRIORITY={'contributor':0,'function':1,'class':1,'file':2,'module':3}
DEFAULT_MAX_NODES=5000
DEFAULT_MIN_WEIGHT=1.0
DEFAULT_CO_CHANGE_DAYS=365
@dataclass
class Node:
    id:str; type:str; path:str; lang:str; loc:int; extra:dict[str,Any]=field(default_factory=dict)
@dataclass
class Edge:
    src:str; dst:str; type:str; weight:float=1.0

def _log(payload:dict[str,Any])->None: sys.stderr.write(json.dumps(payload,ensure_ascii=True)+'\n')
def _error(message:str,file:str='')->None: _log({'error':message,'file':file})
def _is_url(source:str)->bool: return source.startswith('http://') or source.startswith('https://')

def _prepare_source(source:str):
    if _is_url(source):
        tmp=tempfile.TemporaryDirectory(prefix='repo-graph-')
        dst=Path(tmp.name)/'repo'
        proc=subprocess.run(['git','clone','--depth=500',source,str(dst)],capture_output=True,text=True)
        if proc.returncode!=0: raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or 'git clone failed')
        return dst,tmp
    root=Path(source).expanduser().resolve()
    if not root.exists(): raise FileNotFoundError(source)
    return root,None

def _cache_root(source:str)->Path:
    root=Path(tempfile.gettempdir())/'repo-graph'/hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]/'.repo_graph_cache'
    root.mkdir(parents=True,exist_ok=True)
    return root

def _iter_files(root:Path):
    batch=[]
    for dirpath,dirnames,filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        base=Path(dirpath)
        for name in filenames:
            path=base/name
            if path.suffix.lower() not in TEXT_EXTS: continue
            try:
                if b'\0' in path.read_bytes()[:4096]: continue
            except OSError:
                continue
            batch.append(path)
            if len(batch)==100:
                yield batch; batch=[]
    if batch: yield batch

def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def _loc(text:str)->int: return sum(1 for line in text.splitlines() if line.strip())
def _first_comment(text:str)->str|None:
    for line in text.splitlines():
        s=line.strip()
        if not s: continue
        if s.startswith('//'): return s.lstrip('/').strip()
        if s.startswith('#'): return s.lstrip('#').strip()
        if s.startswith('/*'): return s.lstrip('/*').rstrip('*/').strip()
        if s.startswith('*'): return s.lstrip('*').strip()
    return None

def _py_sig(node:ast.AST)->str|None:
    if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)): return None
    args=[a.arg for a in node.args.args]
    if node.args.vararg: args.append('*'+node.args.vararg.arg)
    if node.args.kwarg: args.append('**'+node.args.kwarg.arg)
    return f"{node.name}({', '.join(args)})"

class _PyUsage(ast.NodeVisitor):
    def __init__(self): self.calls=set(); self.refs=set()
    def visit_Call(self,node:ast.Call)->Any:
        fn=node.func
        if isinstance(fn,ast.Name): self.calls.add(fn.id)
        elif isinstance(fn,ast.Attribute): self.calls.add(fn.attr)
        self.generic_visit(node)
    def visit_Name(self,node:ast.Name)->Any:
        if isinstance(node.ctx,ast.Load): self.refs.add(node.id)
    def visit_FunctionDef(self,node): return None
    def visit_AsyncFunctionDef(self,node): return None
    def visit_ClassDef(self,node): return None

def _python_parse(rel:str, source:str)->dict[str,Any]:
    tree=ast.parse(source)
    class_names={n.name for n in ast.walk(tree) if isinstance(n,ast.ClassDef)}
    imports=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): imports.extend(a.name for a in n.names)
        elif isinstance(n,ast.ImportFrom):
            mod='.'*n.level+(n.module or '')
            imports.extend(f'{mod}:{a.name}' if mod else a.name for a in n.names)
    syms=[]
    def walk(stmts, scope):
        for n in stmts:
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                q='.'.join(scope+[n.name]) if scope else n.name
                u=_PyUsage(); [u.visit(s) for s in n.body]
                doc=ast.get_docstring(n,clean=True)
                syms.append({'name':n.name,'kind':'function','qname':q,'start':getattr(n,'lineno',1),'end':getattr(n,'end_lineno',getattr(n,'lineno',1)),'doc':doc.splitlines()[0].strip() if doc else None,'sig':_py_sig(n),'calls':sorted(u.calls),'refs':sorted(name for name in u.refs if name in class_names)})
                walk(n.body, scope+[n.name])
            elif isinstance(n,ast.ClassDef):
                q='.'.join(scope+[n.name]) if scope else n.name
                u=_PyUsage(); [u.visit(s) for s in n.body]
                doc=ast.get_docstring(n,clean=True)
                bases=', '.join(ast.unparse(b) for b in n.bases) if n.bases else ''
                syms.append({'name':n.name,'kind':'class','qname':q,'start':getattr(n,'lineno',1),'end':getattr(n,'end_lineno',getattr(n,'lineno',1)),'doc':doc.splitlines()[0].strip() if doc else None,'sig':f'class {n.name}({bases})' if bases else f'class {n.name}','calls':sorted(u.calls),'refs':sorted(u.refs)})
                walk(n.body, scope+[n.name])
    walk(tree.body if isinstance(tree,ast.Module) else [], [])
    return {'path':rel,'lang':'python','loc':_loc(source),'raw_imports':imports,'symbols':syms}
TS_DEF={'javascript':{'function_declaration','generator_function_declaration','class_declaration','method_definition'},'typescript':{'function_declaration','generator_function_declaration','class_declaration','method_definition'},'go':{'function_declaration','method_declaration','type_spec'},'rust':{'function_item','struct_item','enum_item','trait_item'},'java':{'class_declaration','interface_declaration','enum_declaration','method_declaration','constructor_declaration'}}
TS_CLASS={'javascript':{'class_declaration'},'typescript':{'class_declaration'},'go':{'type_spec'},'rust':{'struct_item','enum_item','trait_item'},'java':{'class_declaration','interface_declaration','enum_declaration'}}
TS_CALL={'javascript':{'call_expression','new_expression'},'typescript':{'call_expression','new_expression'},'go':{'call_expression'},'rust':{'call_expression'},'java':{'method_invocation','object_creation_expression'}}
TS_IMPORT={'javascript':{'import_statement'},'typescript':{'import_statement'},'go':{'import_spec'},'rust':{'use_declaration','extern_crate_declaration'},'java':{'import_declaration'}}
TS_IDENT={'identifier','field_identifier','type_identifier','scoped_identifier','qualified_identifier','property_identifier','module_identifier','package_identifier'}

def _ts_text(src:bytes,node:Any)->str: return src[node.start_byte:node.end_byte].decode('utf-8',errors='replace')
def _ts_name(src:bytes,node:Any)->str|None:
    n=node.child_by_field_name('name')
    if n is not None:
        t=_ts_text(src,n).strip()
        if t: return t
    for ch in node.children:
        if ch.type in TS_IDENT:
            t=_ts_text(src,ch).strip()
            if t: return t
    return None

def _ts_walk_defs(src:bytes,node:Any,lang:str,scope:list[str],out:list[tuple[Any,str,str]]):
    if node.type in TS_DEF.get(lang,set()):
        name=_ts_name(src,node)
        if name:
            kind='class' if node.type in TS_CLASS.get(lang,set()) else 'function'
            q='.'.join(scope+[name]) if scope else name
            out.append((node,kind,q))
            body=node.child_by_field_name('body') or node
            for ch in body.children: _ts_walk_defs(src,ch,lang,scope+[name],out)
        return
    for ch in node.children: _ts_walk_defs(src,ch,lang,scope,out)

def _ts_collect_usage(src:bytes,node:Any,lang:str,class_names:set[str],calls:set[str],refs:set[str]):
    if node.type in TS_DEF.get(lang,set()): return
    if node.type in TS_CALL.get(lang,set()):
        callee=node.child_by_field_name('function') or node.child_by_field_name('name') or node.child_by_field_name('callee') or (node.children[0] if node.children else None)
        if callee is not None:
            name=_ts_name(src,callee)
            if name:
                calls.add(name)
                if name in class_names: refs.add(name)
    if node.type in TS_IDENT:
        t=_ts_text(src,node).strip()
        if t in class_names: refs.add(t)
    for ch in node.children: _ts_collect_usage(src,ch,lang,class_names,calls,refs)

def _tree_parse(rel:str, source:str, lang:str)->dict[str,Any]|None:
    if get_ts_parser is None: return None
    parser=get_ts_parser(lang)
    src=source.encode('utf-8',errors='replace')
    root=parser.parse(src).root_node
    defs=[]; _ts_walk_defs(src,root,lang,[],defs)
    class_names={q.split('.')[-1] for _,kind,q in defs if kind=='class'}
    imports=[]; stack=[root]
    while stack:
        node=stack.pop()
        if node.type in TS_IMPORT.get(lang,set()): imports.append(_ts_text(src,node).strip())
        stack.extend(reversed(node.children))
    syms=[]
    for node,kind,q in defs:
        calls=set(); refs=set(); _ts_collect_usage(src,node.child_by_field_name('body') or node,lang,class_names,calls,refs)
        text=_ts_text(src,node)
        syms.append({'name':q.split('.')[-1],'kind':kind,'qname':q,'start':int(node.start_point[0])+1,'end':int(node.end_point[0])+1,'doc':_first_comment(text),'sig':text.splitlines()[0].strip() if text.splitlines() else None,'calls':sorted(calls),'refs':sorted(refs)})
    return {'path':rel,'lang':lang,'loc':_loc(source),'raw_imports':imports,'symbols':syms}

def _parse_file(path:Path, root:Path, cache_dir:Path)->dict[str,Any]|None:
    rel=path.relative_to(root).as_posix(); lang=LANG_BY_EXT.get(path.suffix.lower())
    if not lang: return None
    fh=cache_dir/f'{_sha(path)}.json'
    if fh.exists():
        try: return json.loads(fh.read_text(encoding='utf-8'))
        except Exception: pass
    try: src=path.read_text(encoding='utf-8',errors='replace')
    except OSError as exc: _error(str(exc),rel); return None
    try: item=_python_parse(rel,src) if lang=='python' else _tree_parse(rel,src,lang)
    except Exception as exc: _error(f'parse failed: {exc}',rel); return None
    if item is None: _error('tree-sitter unavailable; skipping non-Python file',rel); return None
    fh.write_text(json.dumps(item,ensure_ascii=True),encoding='utf-8')
    return item

def _build_nodes(files:list[dict[str,Any]]):
    nodes=[]; sym_index=defaultdict(list); file_index=defaultdict(list)
    for f in files:
        fn=Node(id=f['path'],type='file',path=f['path'],lang=f['lang'],loc=f['loc'],extra={'name':Path(f['path']).name}); nodes.append(fn); file_index[fn.path].append(fn)
        for s in f['symbols']:
            n=Node(id=f"{f['path']}::{s['qname']}",type=s['kind'],path=f['path'],lang=f['lang'],loc=max(0,s['end']-s['start']+1),extra={'name':s['name'],'qname':s['qname'],'start':s['start'],'end':s['end'],'doc':s['doc'],'sig':s['sig']}); nodes.append(n); sym_index[s['name']].append(n); sym_index[s['qname']].append(n)
    return nodes,sym_index,file_index

def _resolve_symbol(source_path:str,name:str,index)->Node|None:
    cands=list(index.get(name,[]))
    if not cands and '.' in name: cands=list(index.get(name.split('.')[-1],[]))
    if not cands: return None
    same=[n for n in cands if n.path==source_path]
    return same[0] if same else (cands[0] if len(cands)==1 else None)

def _resolve_import(raw:str,source_path:str,file_index)->Node|None:
    mod=raw.strip().rstrip(';')
    if mod.startswith('import '):
        mod=mod[7:].strip()
        if ' from ' in mod:
            mod=mod.split(' from ',1)[1].strip()
    if mod.startswith('use '):
        mod=mod[4:].strip()
    if mod.startswith('extern crate '):
        mod=mod[13:].strip()
    mod=mod.strip().strip('"').strip("'").split(':',1)[0]
    if not mod: return None
    if mod.startswith('.'):
        level=len(mod)-len(mod.lstrip('.')); tail=mod.lstrip('.'); parent=Path(source_path).parent
        for _ in range(max(0,level-1)): parent=parent.parent
        base=parent/Path(tail.replace('.','/')) if tail else parent
    else:
        base=Path(mod.replace('.','/'))
    candidates=[base.as_posix()]
    if not base.suffix:
        for ext in TEXT_EXTS: candidates += [(base.with_suffix(ext)).as_posix(),(base/f'index{ext}').as_posix(),(base/f'__init__{ext}').as_posix()]
    for c in candidates:
        if c in file_index: return file_index[c][0]
    return None

def _edges(files:list[dict[str,Any]], sym_index, file_index):
    edges=[]
    for f in files:
        for raw in f['raw_imports']:
            tgt=_resolve_import(raw,f['path'],file_index)
            if tgt is not None and tgt.id!=f['path']: edges.append(Edge(src=f['path'],dst=tgt.id,type='imports',weight=1.0))
        for s in f['symbols']:
            sid=f"{f['path']}::{s['qname']}"
            for name in s['calls']:
                tgt=_resolve_symbol(f['path'],name,sym_index)
                if tgt is not None and tgt.id!=sid: edges.append(Edge(src=sid,dst=tgt.id,type='references' if tgt.type=='class' else 'calls',weight=1.0))
            for name in s['refs']:
                tgt=_resolve_symbol(f['path'],name,sym_index)
                if tgt is not None and tgt.type=='class' and tgt.id!=sid: edges.append(Edge(src=sid,dst=tgt.id,type='references',weight=1.0))
    return edges

def _git_co_change(root:Path,file_nodes:list[Node],since_days:int):
    known={n.path for n in file_nodes}
    try:
        p=subprocess.run(['git','log','--name-only','--pretty=format:%H|%ae',f'--since={since_days}d'],cwd=root,capture_output=True,text=True,check=True)
    except Exception as exc:
        _log({'event':'git_log_skipped','reason':str(exc)}); return [],[]
    cc=Counter(); pairs=Counter(); email=None; files=set()
    def flush():
        nonlocal email,files
        if email and files:
            fs=sorted(files)
            for f in fs: cc[(email,f)] += 1
            for a,b in itertools.combinations(fs,2): pairs[(a,b)] += 1
        email=None; files=set()
    for line in p.stdout.splitlines():
        if not line.strip(): flush(); continue
        if '|' in line and len(line.split('|',1)[0])>=8: flush(); _,email=line.split('|',1); continue
        c=line.strip().replace('\\','/')
        if c in known: files.add(c)
    flush()
    contrib=[Node(id=e,type='contributor',path=e,lang='',loc=0,extra={'email':e}) for e,_ in cc]
    edges=[Edge(src=a,dst=b,type='co_change',weight=float(w)) for (a,b),w in pairs.items() if w>=2] + [Edge(src=e,dst=f,type='references',weight=float(w)) for (e,f),w in cc.items()]
    return contrib,edges

def _semantic(files:list[dict[str,Any]]):
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:
        _log({'event':'semantic_similarity_skipped','reason':str(exc)}); return []
    items=[]
    for f in files:
        for s in f['symbols']:
            text='\n'.join(part for part in [s.get('sig') or s['name'], s.get('doc') or ''] if part).strip()
            if text: items.append({'id':f"{f['path']}::{s['qname']}",'lang':f['lang'],'text':text})
    if len(items)<2: return []
    model=SentenceTransformer('all-MiniLM-L6-v2')
    edges=[]; by_lang=defaultdict(list)
    for i in items: by_lang[i['lang']].append(i)
    for group in by_lang.values():
        if len(group)<2: continue
        emb=model.encode([i['text'] for i in group],convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False)
        sim=emb@emb.T
        for i in range(len(group)):
            for j in range(i+1,len(group)):
                score=float(sim[i,j])
                if score>=0.75: edges.append(Edge(src=group[i]['id'],dst=group[j]['id'],type='semantic_sim',weight=score))
    return edges

def _prune(nodes:list[Node],edges:list[Edge],min_weight:float,max_nodes:int):
    before_n,before_e=len(nodes),len(edges)
    edges=[e for e in edges if e.weight>=min_weight]
    def deg():
        d={n.id:0 for n in nodes}
        for e in edges:
            if e.src in d: d[e.src]+=1
            if e.dst in d: d[e.dst]+=1
        return d
    while True:
        d=deg(); iso={n.id for n in nodes if d.get(n.id,0)==0}
        if not iso: break
        nodes=[n for n in nodes if n.id not in iso]
        edges=[e for e in edges if e.src not in iso and e.dst not in iso]
    while len(nodes)>max_nodes:
        d=deg(); drop=sorted(nodes,key=lambda n:(d.get(n.id,0),NODE_PRIORITY.get(n.type,99),n.loc,n.id))[0].id
        nodes=[n for n in nodes if n.id!=drop]
        edges=[e for e in edges if e.src!=drop and e.dst!=drop]
    _log({'event':'prune_delta','nodes_before':before_n,'nodes_after':len(nodes),'edges_before':before_e,'edges_after':len(edges)})
    return nodes,edges,{'nodes_before':before_n,'nodes_after':len(nodes),'edges_before':before_e,'edges_after':len(edges)}

def _payload(repo:str,nodes:list[Node],edges:list[Edge],extra:dict[str,Any]|None=None):
    meta={'repo':repo,'generated_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'nodes':len(nodes),'edges':len(edges)}
    if extra: meta.update(extra)
    return {'meta':meta,'nodes':[dataclasses.asdict(n) for n in nodes],'edges':[dataclasses.asdict(e) for e in edges]}

def _positions(nodes:list[Node]):
    rings={'contributor':440.0,'file':300.0,'function':160.0,'class':160.0,'module':240.0}
    groups=defaultdict(list)
    for n in nodes: groups[n.type].append(n)
    pos={}; cx,cy=750.0,500.0
    for kind,group in groups.items():
        r=rings.get(kind,240.0)
        for i,n in enumerate(sorted(group,key=lambda x:x.id)):
            a=(i/max(1,len(group)))*math.tau
            pos[n.id]=(cx+r*math.cos(a), cy+r*math.sin(a))
    return pos

def _render_html(graph:dict[str,Any])->str:
    nodes=[Node(**{k:node[k] for k in ('id','type','path','lang','loc')},extra={k:v for k,v in node.items() if k not in {'id','type','path','lang','loc'}}) for node in graph['nodes']]
    pos=_positions(nodes)
    def ncolor(t:str)->str: return {'file':'#60a5fa','function':'#34d399','class':'#f59e0b','contributor':'#f472b6'}.get(t,'#cbd5e1')
    def ecolor(t:str)->str: return {'imports':'#93c5fd','calls':'#34d399','references':'#f59e0b','co_change':'#f472b6','semantic_sim':'#a78bfa'}.get(t,'#94a3b8')
    el=[]
    for e in graph['edges']:
        if e['src'] not in pos or e['dst'] not in pos: continue
        x1,y1=pos[e['src']]; x2,y2=pos[e['dst']]
        el.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{ecolor(e["type"])}" stroke-opacity="0.35" stroke-width="{max(1.0,e["weight"]**0.5):.2f}"/>')
    nl=[]
    for n in nodes:
        x,y=pos[n.id]; label=html.escape(n.extra.get('name') or Path(n.path).name or n.id)
        nl.append(f'<g><title>{html.escape(json.dumps(n.extra,ensure_ascii=True))}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="{5 if n.type=="file" else 7}" fill="{ncolor(n.type)}"/><text x="{x+10:.1f}" y="{y+4:.1f}" fill="#cbd5e1" font-size="11">{label}</text></g>')
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>repo-graph</title><style>body{{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;background:#020617;color:#e2e8f0}}header{{padding:16px 20px;background:linear-gradient(135deg,#111827,#1e293b);border-bottom:1px solid rgba(148,163,184,.2)}}h1{{margin:0;font-size:18px}}.sub{{color:#94a3b8;font-size:13px;margin-top:4px}}.wrap{{display:grid;grid-template-columns:1fr 280px;height:calc(100vh - 68px)}}svg{{width:100%;height:100%;background:radial-gradient(circle at top,rgba(59,130,246,.10),transparent 45%)}}aside{{padding:16px;border-left:1px solid rgba(148,163,184,.2);background:rgba(15,23,42,.92);overflow:auto}}.legend-item{{display:flex;align-items:center;gap:8px;margin:8px 0;font-size:13px;color:#cbd5e1}}.dot{{width:10px;height:10px;border-radius:999px;display:inline-block}}pre{{white-space:pre-wrap;font-size:12px;color:#cbd5e1}}</style></head><body><header><h1>repo-graph</h1><div class="sub">Self-contained SVG view generated locally</div></header><div class="wrap"><svg viewBox="0 0 1500 1000" xmlns="http://www.w3.org/2000/svg"><g>{''.join(el)}</g><g>{''.join(nl)}</g></svg><aside><div class="legend-item"><span class="dot" style="background:#60a5fa"></span> file</div><div class="legend-item"><span class="dot" style="background:#34d399"></span> function</div><div class="legend-item"><span class="dot" style="background:#f59e0b"></span> class</div><div class="legend-item"><span class="dot" style="background:#f472b6"></span> contributor</div><pre>{html.escape(json.dumps(graph["meta"],ensure_ascii=True,indent=2))}</pre></aside></div></body></html>'''

def _summary(nodes:list[Node],edges:list[Edge])->str:
    nc=Counter(n.type for n in nodes); ec=Counter(e.type for e in edges)
    def table(title:str,counts:Counter[str]):
        out=[title,f"{'type':<16} {'count':>8}"]
        for key,val in sorted(counts.items(),key=lambda item:(-item[1],item[0])): out.append(f"{key:<16} {val:>8}")
        if len(out)==2: out.append('(empty)')
        return out
    return '\n'.join(table('Node Types',nc)+['']+table('Edge Types',ec))+'\n'

def run_pipeline(source:str,*,output_dir:str|Path='.',since_days:int=DEFAULT_CO_CHANGE_DAYS,min_weight:float=DEFAULT_MIN_WEIGHT,max_nodes:int=DEFAULT_MAX_NODES)->dict[str,Any]:
    root,tmp=_prepare_source(source)
    try:
        cache=_cache_root(source)
        files=[]
        for batch in _iter_files(root):
            for path in batch:
                rel=path.relative_to(root).as_posix(); lang=LANG_BY_EXT.get(path.suffix.lower())
                if not lang: continue
                fh=cache/f'{_sha(path)}.json'
                if fh.exists():
                    try: files.append(json.loads(fh.read_text(encoding='utf-8'))); continue
                    except Exception: pass
                try: text=path.read_text(encoding='utf-8',errors='replace')
                except OSError as exc: _error(str(exc),rel); continue
                try: item=_python_parse(rel,text) if lang=='python' else _tree_parse(rel,text,lang)
                except Exception as exc: _error(f'parse failed: {exc}',rel); continue
                if item is None: _error('tree-sitter unavailable; skipping non-Python file',rel); continue
                fh.write_text(json.dumps(item,ensure_ascii=True),encoding='utf-8'); files.append(item)
        nodes,sym_index,file_index=_build_nodes(files)
        edges=_edges(files,sym_index,file_index)
        contrib,co=_git_co_change(root,[n for n in nodes if n.type=='file'],since_days)
        nodes.extend(contrib); edges.extend(co); edges.extend(_semantic(files))
        nodes,edges,prune=_prune(nodes,edges,min_weight,max_nodes)
        graph=_payload(source,nodes,edges,{'prune':prune})
        out=Path(output_dir).resolve()
        try:
            if out.is_relative_to(root):
                out=Path(tempfile.gettempdir())/'repo-graph-output'/hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]
        except AttributeError:
            pass
        from .output import render_summary, write_graph
        write_graph(graph, out)
        sys.stdout.write(render_summary(graph))
        return graph
    finally:
        if tmp is not None: tmp.cleanup()

def build_knowledge_graph(source:str,*,since_days:int=DEFAULT_CO_CHANGE_DAYS,min_weight:float=DEFAULT_MIN_WEIGHT,max_nodes:int=DEFAULT_MAX_NODES)->dict[str,Any]:
    return run_pipeline(source,since_days=since_days,min_weight=min_weight,max_nodes=max_nodes)

