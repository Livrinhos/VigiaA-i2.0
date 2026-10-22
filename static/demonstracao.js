'use strict';

const $ = (id) => document.getElementById(id);
const nomesEpi = {capacete:'Capacete',oculos:'Óculos de proteção',colete:'Colete',luvas:'Luvas',mascara:'Máscara'};
const estadosEpi = {presente:'detectado',inconclusivo:'inconclusivo',observando:'verificando',possivel_ausencia:'possível ausência'};
const rotulosEventos = {queda_observada:'Possível queda',possivel_colapso:'Possível colapso',encontrada_caida_imovel:'Pessoa deitada e imóvel'};
let estadoCentral = null, ocupadoCentral = false, modoCentral = 'video', politicaInicializada = false;
let ultimaListaPessoas = '', ultimaListaEventos = '', imagemUrl = null, imagemTag = null, arrastandoTempo = false;

function tempo(segundos) {
  if (!Number.isFinite(segundos)) return '—';
  segundos = Math.max(0, Math.floor(segundos));
  const partes = [Math.floor(segundos / 60) % 60, segundos % 60].map(n => String(n).padStart(2,'0'));
  if (segundos >= 3600) partes.unshift(String(Math.floor(segundos / 3600)).padStart(2,'0'));
  return partes.join(':');
}

function avisar(mensagem, erro = false) {
  $('feedbackCentral').textContent = mensagem;
  $('feedbackCentral').className = 'feedback' + (erro ? ' erro' : '');
  $('feedbackCentral').hidden = !mensagem;
}

async function api(url, dados, metodo = 'POST') {
  const controle = new AbortController();
  const limite = setTimeout(() => controle.abort(), 45000);
  try {
    const resposta = await fetch(url, {method:metodo,cache:'no-store',signal:controle.signal,
      headers: metodo === 'GET' ? {} : {'Content-Type':'application/json','X-VigiaAI':'1'},
      ...(metodo === 'GET' ? {} : {body:JSON.stringify(dados || {})})});
    const retorno = await resposta.json();
    if (!resposta.ok || retorno.ok === false) throw new Error(retorno.mensagem || 'Não foi possível completar a solicitação.');
    return retorno;
  } finally { clearTimeout(limite); }
}

function atualizarControles() {
  const s = estadoCentral, video = s?.fonte?.modo === 'video', ativo = !!s?.executando;
  $('iniciarAnalise').disabled = ocupadoCentral || !s?.fonte || (ativo && !s.pausado);
  $('iniciarAnalise').textContent = s?.pausado ? '▶ Retomar análise' : s?.estado === 'concluido' ? '▶ Analisar novamente' : '▶ Iniciar análise';
  $('pausarAnalise').disabled = ocupadoCentral || !video || !ativo || s.pausado || s.estado === 'reposicionando';
  $('reiniciarAnalise').disabled = ocupadoCentral || !video;
  $('encerrarAnalise').disabled = ocupadoCentral || (!s?.fonte && !ativo);
  $('linhaTempo').disabled = ocupadoCentral || !video || s?.estado === 'iniciando';
  for (const id of ['modoVideo','modoCamera','buscarCameras','salvarPolitica','selecionarNoPalco','arquivoVideo']) $(id).disabled = ocupadoCentral;
  $('cameraSelecionada').disabled = ocupadoCentral || $('cameraSelecionada').options.length < 2 || ativo;
  $('areaUpload').setAttribute('aria-disabled', String(ocupadoCentral || ativo));
  $('exportarHistorico').disabled = !s?.eventos?.length;
}

function criar(tag, classe, texto) {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (texto !== undefined) e.textContent = texto;
  return e;
}

function renderizarPessoas(pessoas) {
  const chave = JSON.stringify(pessoas);
  if (chave === ultimaListaPessoas) return;
  ultimaListaPessoas = chave;
  const area = $('pessoasCentral'); area.replaceChildren();
  if (!pessoas.length) {
    const vazio = criar('div','empty-people');
    vazio.append(criar('p','','Nenhuma pessoa em observação.'),criar('small','','Os resultados aparecerão durante a análise.'));
    area.append(vazio); return;
  }
  for (const p of pessoas) {
    const card = criar('article','person-card' + (p.emergencia ? ' emergency' : ''));
    const titulo = criar('div','person-heading');
    titulo.append(criar('strong','',`Pessoa ${p.id}`),criar('span','',p.rastreamento_confiavel === false ? 'Associação inconclusiva' : 'ID temporário'));
    card.append(titulo,criar('p','person-state',p.situacao_rotulo || p.postura || 'Situação inconclusiva'));
    const badges = criar('div','person-badges');
    for (const [epi,estado] of Object.entries(p.epis || {})) badges.append(criar('span','epi-badge ' + estado,`${nomesEpi[epi] || epi}: ${estadosEpi[estado] || estado}`));
    if (!badges.children.length) badges.append(criar('span','epi-badge','Nenhum EPI selecionado'));
    card.append(badges,criar('p','person-reason',p.situacao_motivo || p.postura_motivo || ''));
    area.append(card);
  }
}

function renderizarEventos(eventos, fonte) {
  const chave = JSON.stringify([eventos,fonte?.id]);
  if (chave === ultimaListaEventos) return;
  ultimaListaEventos = chave;
  const area = $('historicoEventos'); area.replaceChildren();
  $('totalHistorico').textContent = `${eventos.length} evento${eventos.length === 1 ? '' : 's'}`;
  if (!eventos.length) {
    const linha = criar('tr'), celula = criar('td'); celula.colSpan = 5;
    const vazio = criar('div','empty-history');
    vazio.append(criar('strong','','Nenhuma ocorrência registrada.'),criar('span','','Eventos reais da análise aparecerão aqui, com seu contexto.'));
    celula.append(vazio); linha.append(celula); area.append(linha); return;
  }
  for (const e of eventos) {
    const linha = criar('tr');
    const tipo = criar('td');
    tipo.append(criar('div','event-type ' + e.tipo,e.tipo === 'epi' ? 'Possível ausência de EPI' : rotulosEventos[e.classificacao] || 'Situação suspeita'));
    tipo.append(criar('small','',e.fonte_nome || 'Fonte local'));
    const pessoa = criar('td','',`Pessoa ${e.pessoa_id}`);
    const instante = criar('td','',e.tempo_video == null ? 'Ao vivo' : tempo(e.tempo_video) + ' no vídeo');
    instante.append(criar('small','',e.data));
    const motivo = criar('td','',e.motivo);
    motivo.append(criar('small','','Verificação humana pendente · ' + (e.email || 'sem envio de e-mail')));
    const acaoCelula = criar('td'), botao = criar('button','quiet','Rever trecho ↗');
    botao.disabled = !fonte || fonte.modo !== 'video' || fonte.id !== e.fonte_id || e.tempo_video == null;
    botao.title = botao.disabled ? 'O vídeo desta ocorrência não está selecionado.' : 'Abrir contexto anterior ao evento; a análise fica pausada.';
    botao.addEventListener('click',() => acaoCentral('buscar',{segundos:Math.max(0,e.tempo_video - 3)}));
    acaoCelula.append(botao); linha.append(tipo,pessoa,instante,motivo,acaoCelula); area.append(linha);
  }
}

function renderizarEstado(s) {
  estadoCentral = s;
  if (s.fonte && s.fonte.modo !== modoCentral) mostrarModo(s.fonte.modo);
  const estado = s.pausado && s.executando ? 'pausado' : s.estado;
  const labels = {parado:'Aguardando fonte',pronto:'Pronto para analisar',iniciando:'Carregando IA',ativo:'Análise em andamento',pausado:'Análise pausada',concluido:'Análise concluída',erro:'Verificar sistema',parando:'Encerrando',reposicionando:'Buscando trecho'};
  $('estadoSistema').className = 'status-chip ' + estado;
  $('estadoSistema').textContent = labels[estado] || estado;
  $('mensagemSistema').textContent = s.mensagem + (s.aviso ? ' ' + s.aviso : '') + (s.aviso_desempenho ? ' ' + s.aviso_desempenho : '');
  const i = s.indicadores;
  for (const [id,chave] of Object.entries({metricaPessoas:'pessoas',metricaEpis:'epis',metricaInconclusivos:'inconclusivos',metricaAusencias:'ausencias',metricaEmergencias:'emergencias',metricaOcorrencias:'ocorrencias'})) $(id).textContent = i[chave];
  $('contagemPessoas').textContent = i.pessoas;
  $('fpsOverlay').textContent = `${Number(s.fps || 0).toFixed(1)} fps de processamento`;
  $('tempoIA').textContent = `IA acumulada: ${Number(s.tempo_ia_segundos || 0).toFixed(1)} s`;
  $('dispositivoIA').textContent = `Dispositivo: ${s.dispositivo === '0' ? 'CUDA · GPU 0' : s.dispositivo || 'a carregar'}`;
  $('rotuloFonte').textContent = s.fonte?.nome || 'Nenhuma fonte selecionada';
  $('tipoQuadro').textContent = s.estado === 'reposicionando' ? 'REPOSICIONANDO · NOVO CONTEXTO TEMPORAL' : !s.quadro_analisado ? (s.executando ? 'PRÉVIA · MODELOS CARREGANDO' : 'PRÉVIA · IA NÃO INICIADA') : s.estado === 'erro' ? 'ÚLTIMO QUADRO · ANÁLISE INTERROMPIDA' : s.pausado ? 'ANÁLISE PAUSADA' : s.estado === 'concluido' ? 'ANÁLISE CONCLUÍDA' : 'DETECÇÕES REAIS · VIGIAAI';
  const video = s.fonte?.modo === 'video';
  $('tempoVideo').textContent = video ? `${tempo(s.tempo_video || 0)} / ${tempo(s.fonte.duracao_segundos)}` : s.fonte ? 'CÂMERA AO VIVO' : '00:00 / 00:00';
  $('progressoTexto').textContent = video ? `${((s.progresso || 0) * 100).toFixed(1)}% do vídeo percorrido` : s.fonte ? 'Transmissão ao vivo' : 'Aguardando vídeo';
  $('quadrosTexto').textContent = `${s.quadros_processados || 0} quadros analisados${video ? ` · fonte ${s.fonte.fps_original.toFixed(1)} fps` : ''}`;
  if (!arrastandoTempo) {
    $('linhaTempo').max = video ? Math.max(0,s.fonte.duracao_segundos - 1 / s.fonte.fps_original) : 1;
    $('linhaTempo').value = video ? s.tempo_video || 0 : 0;
  }
  $('formatosUpload').textContent = `MP4, AVI, MOV, MKV, WebM · até ${Math.floor(s.limite_upload_bytes / 1048576)} MB`;
  const info = $('informacoesVideo'); info.replaceChildren(); info.hidden = !video;
  if (video) {
    info.append(criar('strong','',s.fonte.nome),criar('div','',`${s.fonte.largura} × ${s.fonte.altura} · ${tempo(s.fonte.duracao_segundos)} · ${(s.fonte.tamanho_bytes / 1048576).toFixed(1)} MB`));
  }
  if (!s.imagem_disponivel) {
    $('quadroProcessado').hidden = true; $('estadoVazio').hidden = false;
    $('hudQuadro').hidden = $('legendaQuadro').hidden = true;
  }
  if (!politicaInicializada) {
    const itens = s.politica_configurada ? s.epi_obrigatorio : ['capacete','oculos'];
    document.querySelectorAll('input[name="epiCentral"]').forEach(input => { input.checked = itens.includes(input.value); });
    $('confirmacaoEpi').value = s.confirmacao_segundos;
    politicaInicializada = true;
  }
  $('suporteEpi').textContent = s.epi_ativo ? 'Detector disponível: ' + s.epis_suportados.map(e => nomesEpi[e] || e).join(', ') + '.' : s.epi_erro || 'Os modelos serão carregados ao iniciar a análise.';
  if (s.oculos_erro) $('suporteEpi').textContent += ' ' + s.oculos_erro;
  $('notificacoesStatus').textContent = s.notificacoes_reais ? 'Painel clássico ativo: verifique a configuração de notificações.' : 'Demonstração local · sem envio de e-mails ou fotos de ocorrências';
  renderizarPessoas(s.deteccoes); renderizarEventos(s.eventos,s.fonte); atualizarControles();
}

async function consultarEstado() { renderizarEstado(await api('/api/central/estado',null,'GET')); }

async function aplicarPolitica() {
  const itens = Array.from(document.querySelectorAll('input[name="epiCentral"]:checked'),e => e.value);
  await api('/configurar-epi',{obrigatorios:itens,confirmacao_segundos:Number($('confirmacaoEpi').value)});
  $('salvarPolitica').textContent = 'Aplicar';
}

async function acaoCentral(acao,dados = {}) {
  if (ocupadoCentral) return;
  ocupadoCentral = true; atualizarControles();
  try {
    if (acao === 'iniciar' && !estadoCentral?.pausado) await aplicarPolitica();
    await api('/api/central/acao/' + acao,dados);
    avisar(acao === 'buscar' ? 'Trecho carregando. A continuidade temporal será reconstruída ao retomar.' : '');
    if (acao === 'encerrar') imagemTag = null;
    await consultarEstado();
  } catch (e) { avisar(e.name === 'AbortError' ? 'O sistema demorou a responder. Consulte o estado antes de tentar novamente.' : e.message,true); }
  finally { ocupadoCentral = false; atualizarControles(); }
}

async function trocarModo(modo) {
  if (ocupadoCentral || modo === modoCentral) return;
  if (estadoCentral?.fonte || estadoCentral?.executando) {
    await acaoCentral('encerrar');
    if (estadoCentral?.fonte || estadoCentral?.executando) return;
  }
  mostrarModo(modo);
}

function mostrarModo(modo) {
  modoCentral = modo;
  $('opcoesVideo').hidden = modo !== 'video'; $('opcoesCamera').hidden = modo !== 'camera';
  for (const [id,selecionado] of [['modoVideo',modo === 'video'],['modoCamera',modo === 'camera']]) {
    $(id).classList.toggle('selected',selecionado); $(id).setAttribute('aria-pressed',String(selecionado));
  }
  $('modoAtual').replaceChildren(criar('span','',modo === 'video' ? 'Vídeo gravado' : 'Câmera ao vivo'));
  $('tituloVazio').textContent = modo === 'video' ? 'Seu vídeo, sob uma nova perspectiva.' : 'Uma visão em tempo real.';
  $('textoVazio').textContent = modo === 'video' ? 'Selecione uma gravação para acompanhar pessoas, EPIs e possíveis ocorrências.' : 'Busque e selecione uma câmera acessível ao servidor para iniciar o monitoramento.';
  $('selecionarNoPalco').textContent = modo === 'video' ? 'Selecionar vídeo' : 'Buscar câmeras';
}

async function enviarVideo(arquivo) {
  if (!arquivo || ocupadoCentral) return;
  if (estadoCentral?.executando) { avisar('Encerre a análise atual antes de enviar outro vídeo.',true); return; }
  if (!/\.(mp4|avi|mov|mkv|webm)$/i.test(arquivo.name)) { avisar('Selecione um vídeo MP4, AVI, MOV, MKV ou WebM.',true); return; }
  if (arquivo.size > (estadoCentral?.limite_upload_bytes || 512 * 1048576)) { avisar('O arquivo ultrapassa o limite de tamanho informado.',true); return; }
  ocupadoCentral = true; atualizarControles(); avisar('Enviando e verificando o vídeo…');
  const progresso = $('progressoUpload'); progresso.hidden = false; progresso.value = 0;
  try {
    await new Promise((resolve,reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST','/api/central/videos'); xhr.setRequestHeader('X-VigiaAI','1'); xhr.timeout = 300000;
      xhr.upload.onprogress = e => { if (e.lengthComputable) progresso.value = e.loaded * 100 / e.total; };
      xhr.onload = () => { try { const r = JSON.parse(xhr.responseText); if (xhr.status >= 400 || !r.ok) throw new Error(r.mensagem || 'Vídeo não aceito.'); resolve(r); } catch(e) { reject(e); } };
      xhr.onerror = () => reject(new Error('Falha de conexão durante o envio.'));
      xhr.ontimeout = () => reject(new Error('O envio excedeu o tempo limite.'));
      const dados = new FormData(); dados.append('video',arquivo); xhr.send(dados);
    });
    imagemTag = null; await consultarEstado(); avisar('Vídeo pronto. Confira os EPIs selecionados e inicie a análise.');
  } catch(e) { avisar(e.message,true); }
  finally { progresso.hidden = true; ocupadoCentral = false; $('arquivoVideo').value = ''; atualizarControles(); }
}

async function buscarCameras() {
  if (ocupadoCentral) return;
  ocupadoCentral = true; atualizarControles(); $('cameraMensagem').textContent = 'Verificando dispositivos acessíveis…';
  try {
    const r = await api('/api/central/cameras/buscar');
    const seletor = $('cameraSelecionada'); seletor.replaceChildren(criar('option','',r.resultado.length ? 'Selecione uma câmera' : 'Nenhuma câmera disponível'));
    seletor.firstChild.value = '';
    for (const c of r.resultado) { const op = criar('option','',`${c.nome} · ${c.largura} × ${c.altura}`); op.value = String(c.indice); seletor.append(op); }
    $('cameraMensagem').textContent = r.resultado.length ? `${r.resultado.length} dispositivo(s) responderam. A lista pode incluir câmeras virtuais.` : 'Nenhuma câmera forneceu imagens. Verifique conexão, permissões e outros aplicativos.';
  } catch(e) { avisar(e.message,true); $('cameraMensagem').textContent = 'Não foi possível verificar as câmeras.'; }
  finally { ocupadoCentral = false; atualizarControles(); }
}

async function carregarBiblioteca() {
  try {
    const r = await api('/api/central/biblioteca',null,'GET');
    if (!r.resultado.length) return;
    $('bibliotecaVideos').replaceChildren();
    for (const video of r.resultado) {
      const botao = criar('button','library-item',video.titulo); botao.append(criar('small','',video.descricao || 'Vídeo local autorizado'));
      botao.addEventListener('click',async () => {
        if (ocupadoCentral) return;
        if (modoCentral !== 'video') await trocarModo('video');
        ocupadoCentral = true; atualizarControles();
        try { await api('/api/central/biblioteca/selecionar',{id:video.id}); imagemTag = null; await consultarEstado(); avisar('Vídeo da biblioteca pronto para análise.'); }
        catch(e) { avisar(e.message,true); } finally { ocupadoCentral = false; atualizarControles(); }
      });
      $('bibliotecaVideos').append(botao);
    }
  } catch(e) { $('bibliotecaVideos').replaceChildren(criar('p','library-empty','Biblioteca indisponível: ' + e.message)); }
}

async function cicloEstadoCentral() {
  try { await consultarEstado(); }
  catch(e) { $('estadoSistema').textContent = 'Sem conexão'; $('estadoSistema').className = 'status-chip erro'; $('mensagemSistema').textContent = 'Não foi possível consultar o Flask. Verifique se o servidor continua aberto.'; $('tipoQuadro').textContent = 'ÚLTIMO QUADRO · SEM CONEXÃO'; }
  setTimeout(cicloEstadoCentral,350);
}

async function cicloQuadroCentral() {
  if (estadoCentral?.imagem_disponivel && estadoCentral?.estado !== 'reposicionando') {
    const fonteDaRequisicao = estadoCentral?.fonte?.id;
    const controle = new AbortController(); const limite = setTimeout(() => controle.abort(),5000);
    try {
      const r = await fetch('/api/central/quadro.jpg',{cache:'no-store',headers:imagemTag ? {'If-None-Match':imagemTag} : {},signal:controle.signal});
      if (r.status === 200) {
        const blob = await r.blob();
        if (estadoCentral?.fonte?.id === fonteDaRequisicao && estadoCentral?.imagem_disponivel) {
          const nova = URL.createObjectURL(blob); $('quadroProcessado').src = nova;
          $('quadroProcessado').hidden = false; $('estadoVazio').hidden = true;
          $('hudQuadro').hidden = $('legendaQuadro').hidden = false;
          if (imagemUrl) URL.revokeObjectURL(imagemUrl); imagemUrl = nova; imagemTag = r.headers.get('ETag');
        }
      }
    } catch (_) { /* O estado do servidor informa falhas; a imagem anterior permanece identificada. */ }
    finally { clearTimeout(limite); }
  }
  setTimeout(cicloQuadroCentral,120);
}

$('modoVideo').addEventListener('click',() => trocarModo('video'));
$('modoCamera').addEventListener('click',() => trocarModo('camera'));
$('selecionarNoPalco').addEventListener('click',() => modoCentral === 'video' ? $('arquivoVideo').click() : buscarCameras());
$('areaUpload').addEventListener('click',() => { if (!ocupadoCentral && !estadoCentral?.executando) $('arquivoVideo').click(); });
$('areaUpload').addEventListener('keydown',e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('areaUpload').click(); } });
$('arquivoVideo').addEventListener('change',e => enviarVideo(e.target.files[0]));
for (const nome of ['dragenter','dragover']) $('areaUpload').addEventListener(nome,e => { e.preventDefault(); $('areaUpload').classList.add('drag-over'); });
for (const nome of ['dragleave','drop']) $('areaUpload').addEventListener(nome,e => { e.preventDefault(); $('areaUpload').classList.remove('drag-over'); });
$('areaUpload').addEventListener('drop',e => enviarVideo(e.dataTransfer.files[0]));
$('iniciarAnalise').addEventListener('click',() => acaoCentral(estadoCentral?.pausado ? 'retomar' : 'iniciar'));
$('pausarAnalise').addEventListener('click',() => acaoCentral('pausar'));
$('reiniciarAnalise').addEventListener('click',() => acaoCentral('reiniciar'));
$('encerrarAnalise').addEventListener('click',() => acaoCentral('encerrar'));
$('linhaTempo').addEventListener('input',() => { arrastandoTempo = true; $('tempoVideo').textContent = tempo(Number($('linhaTempo').value)) + ' / ' + tempo(estadoCentral?.fonte?.duracao_segundos); });
$('linhaTempo').addEventListener('change',async () => { const t = Number($('linhaTempo').value); await acaoCentral('buscar',{segundos:t}); arrastandoTempo = false; });
$('politicaEpi').addEventListener('input',() => { $('salvarPolitica').textContent = 'Aplicar •'; });
$('politicaEpi').addEventListener('submit',async e => { e.preventDefault(); if (ocupadoCentral) return; ocupadoCentral = true; atualizarControles(); try { await aplicarPolitica(); await consultarEstado(); avisar('Política de EPI aplicada.'); } catch(e) { avisar(e.message,true); } finally { ocupadoCentral = false; atualizarControles(); } });
$('buscarCameras').addEventListener('click',buscarCameras);
$('cameraSelecionada').addEventListener('change',async e => { if (!e.target.value || ocupadoCentral) return; ocupadoCentral = true; atualizarControles(); try { await api('/api/central/camera',{indice:Number(e.target.value)}); await consultarEstado(); avisar('Câmera selecionada. Inicie o monitoramento.'); } catch(e) { avisar(e.message,true); } finally { ocupadoCentral = false; atualizarControles(); } });
$('telaCheia').addEventListener('click',() => { $('palcoVideo').requestFullscreen?.().catch(() => avisar('Tela cheia não está disponível neste navegador.')); });
$('exportarHistorico').addEventListener('click',() => { const a = criar('a'); const url = URL.createObjectURL(new Blob([JSON.stringify({exportado_em:new Date().toISOString(),eventos:estadoCentral.eventos},null,2)],{type:'application/json'})); a.href = url; a.download = 'vigiaai-ocorrencias.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); });

cicloEstadoCentral(); cicloQuadroCentral(); carregarBiblioteca();
