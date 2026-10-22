import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {setTimeout as esperar} from 'node:timers/promises';
import vm from 'node:vm';
import test from 'node:test';

class Elemento {
  constructor(tag='div') { this.tag=tag;this.children=[];this.handlers=new Map();this.textContent='';this.hidden=false;this.disabled=false;this.value='';this.checked=false;this.className='';this.attributes={};
    this.classList={add:(n)=>this.classList.toggle(n,true),remove:(n)=>this.classList.toggle(n,false),toggle:(n,v)=>{const s=new Set(this.className.split(' ').filter(Boolean));v?s.add(n):s.delete(n);this.className=[...s].join(' ');}};
  }
  append(...e) {this.children.push(...e);}
  replaceChildren(...e) {this.children=[...e];}
  get firstChild(){return this.children[0];}
  get options(){return this.children;}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(k,v){this.handlers.set(k,v);}
  click(){return this.handlers.get('click')?.({target:this,preventDefault(){}});}
}

test('central: upload, pessoas/EPIs, pausa, busca, reinício, câmera e encerramento com rotas Flask',async(t)=>{
  const python=process.env.VIGIAAI_PYTHON || fileURLToPath(new URL('../.venv/Scripts/python.exe',import.meta.url));
  const ponte=spawn(python,[fileURLToPath(new URL('api_central.py',import.meta.url))],{stdio:['pipe','pipe','inherit'],windowsHide:true});
  const pendentes=new Map();let id=0;
  createInterface({input:ponte.stdout}).on('line',linha=>{const r=JSON.parse(linha);const p=pendentes.get(r.id);pendentes.delete(r.id);p.resolve(new Response([204,304].includes(r.status)?null:Buffer.from(r.body,'base64'),{status:r.status,headers:r.headers}));});
  ponte.on('error',e=>{for(const p of pendentes.values())p.reject(e);});
  ponte.on('exit',()=>{for(const p of pendentes.values())p.reject(new Error('A ponte Flask encerrou inesperadamente.'));});
  t.after(()=>ponte.stdin.end());
  const buscar=(url,opcoes={})=>new Promise((resolve,reject)=>{const n=++id;pendentes.set(n,{resolve,reject});ponte.stdin.write(JSON.stringify({id:n,url,...opcoes})+'\n');});
  const html=await readFile(new URL('../templates/demonstracao.html',import.meta.url),'utf8');
  const js=await readFile(new URL('../static/demonstracao.js',import.meta.url),'utf8');
  const elementos=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Elemento()]));
  elementos.get('cameraSelecionada').append(new Elemento('option'));
  const inputs=['capacete','oculos','colete','luvas','mascara'].map(value=>Object.assign(new Elemento('input'),{value}));
  const document={getElementById:id=>elementos.get(id),createElement:tag=>new Elemento(tag),querySelectorAll:s=>s.endsWith(':checked')?inputs.filter(e=>e.checked):inputs};
  class XHR {
    constructor(){this.upload={};this.headers={};}
    open(method,url){this.method=method;this.url=url;}
    setRequestHeader(k,v){this.headers[k]=v;}
    async send(form){try{const file=form.get('video');this.upload.onprogress?.({lengthComputable:true,loaded:file.size,total:file.size});const r=await buscar(this.url,{method:this.method,headers:this.headers,arquivo:{nome:file.name,base64:Buffer.from(await file.arrayBuffer()).toString('base64')}});this.status=r.status;this.responseText=await r.text();this.onload();}catch(_){this.onerror();}}
  }
  const contexto=vm.createContext({document,console,URL,AbortController,Blob,File,FormData,XMLHttpRequest:XHR,fetch:buscar,setTimeout:()=>1,clearTimeout:()=>{}});
  vm.runInContext(js,contexto,{filename:'demonstracao.js'});
  const executar=c=>vm.runInContext(c,contexto);
  const ate=async(condicao)=>{const fim=Date.now()+8000;do{await executar('consultarEstado()');if(condicao())return;await esperar(40);}while(Date.now()<fim);assert.fail('O estado da central não chegou no prazo.');};
  await ate(()=>elementos.get('metricaPessoas').textContent===0);
  assert.equal(elementos.get('iniciarAnalise').disabled,true);
  assert.deepEqual(inputs.filter(e=>e.checked).map(e=>e.value),['capacete','oculos']);
  const video=await buscar('/fixture-video');
  contexto.arquivoFixture=new File([await video.arrayBuffer()],'teste.avi');
  await executar('enviarVideo(arquivoFixture)');
  assert.equal(elementos.get('iniciarAnalise').disabled,false);
  assert.match(elementos.get('informacoesVideo').children[0].textContent,/teste.avi/);
  await executar("acaoCentral('iniciar')");
  await ate(()=>elementos.get('metricaPessoas').textContent===1 && elementos.get('metricaEpis').textContent===2);
  assert.equal(elementos.get('pessoasCentral').children.length,1);
  await executar('cicloQuadroCentral()');
  assert.equal(elementos.get('quadroProcessado').hidden,false);
  assert.match(elementos.get('quadroProcessado').src,/^blob:/);
  await executar("acaoCentral('pausar')");await esperar(100);
  const anterior=await executar('estadoCentral.quadros_processados');
  await esperar(150);await executar('consultarEstado()');
  assert.equal(await executar('estadoCentral.quadros_processados'),anterior);
  await executar("acaoCentral('buscar',{segundos:1})");
  await ate(()=>executar('estadoCentral.tempo_video')===1 && executar('estadoCentral.pausado'));
  const segmento=executar('estadoCentral.segmento');
  await executar("acaoCentral('reiniciar')");
  await ate(()=>executar('estadoCentral.segmento')>segmento && executar('estadoCentral.tempo_video')<.2);
  await executar("trocarModo('camera')");
  assert.equal(elementos.get('opcoesCamera').hidden,false);
  await executar('buscarCameras()');
  assert.equal(elementos.get('cameraSelecionada').options.length,2);
  const seletor=elementos.get('cameraSelecionada');seletor.value='0';
  await seletor.handlers.get('change')({target:seletor});
  assert.equal(executar('estadoCentral.fonte.modo'),'camera');
  await executar("acaoCentral('iniciar')");
  await ate(()=>executar('estadoCentral.estado')==='ativo');
  assert.equal(elementos.get('pausarAnalise').disabled,true);
  assert.equal(elementos.get('linhaTempo').disabled,true);
  assert.equal(executar('estadoCentral.notificacoes_reais'),false);
  await executar("acaoCentral('encerrar')");
  assert.equal(executar('estadoCentral.fonte'),null);
  assert.equal(elementos.get('metricaOcorrencias').textContent,0);
  assert.equal(elementos.get('iniciarAnalise').disabled,true);
  // Contratos de apresentação: texto não interpretado como HTML e navegação contextual do evento.
  executar("renderizarPessoas([{id:1,situacao_rotulo:'<script>não executar</script>',epis:{oculos:'inconclusivo'}}])");
  assert.equal(elementos.get('pessoasCentral').children[0].children[1].textContent,'<script>não executar</script>');
  executar("renderizarEventos([{id:'teste',tipo:'queda',classificacao:'queda_observada',pessoa_id:1,fonte_id:'v1',fonte_nome:'Teste',tempo_video:2,motivo:'Evento sintético de teste',data:'22/10/2026'}],{id:'v1',modo:'video'})");
  assert.equal(elementos.get('historicoEventos').children[0].children[4].children[0].disabled,false);
  assert.equal(executar('tempo(3661)'),'01:01:01');
});
