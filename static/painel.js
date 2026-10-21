"use strict";

const elemento = (id) => document.getElementById(id);
let ultimoStatus = null;
let politicaCarregada = false;
let ocupado = false;
let urlImagem = null;

async function requisitar(url, opcoes = {}) {
  const controle = new AbortController();
  const limite = setTimeout(() => controle.abort(), 6000);
  try {
    const resposta = await fetch(url, { cache: "no-store", ...opcoes, signal: controle.signal });
    const dados = await resposta.json();
    if (!resposta.ok) throw new Error(dados.mensagem || "O sistema não concluiu a solicitação.");
    return dados;
  } catch (erro) {
    if (erro.name === "AbortError") throw new Error("O sistema demorou para responder. Tente novamente.");
    throw erro;
  } finally {
    clearTimeout(limite);
  }
}

function feedback(texto, erro = false) {
  const aviso = elemento("feedback");
  aviso.hidden = false;
  aviso.textContent = texto;
  aviso.classList.toggle("erro", erro);
}

function atualizarBotoes() {
  const ativo = Boolean(ultimoStatus && ultimoStatus.executando);
  elemento("iniciar").disabled = ocupado || ativo || !ultimoStatus;
  elemento("parar").disabled = ocupado || !ativo;
  elemento("coletar").disabled = ocupado || !ultimoStatus || !ultimoStatus.coleta_disponivel;
  elemento("salvarEpi").disabled = ocupado || !ultimoStatus;
}

function mostrarPessoas(pessoas) {
  const area = elemento("pessoas");
  area.replaceChildren();
  if (!pessoas.length) {
    const vazio = document.createElement("p");
    vazio.className = "muted";
    vazio.textContent = "Nenhuma pessoa em observação.";
    area.append(vazio);
    return;
  }
  const nomes = { oculos: "Óculos", mascara: "Máscara", capacete: "Capacete", colete: "Colete", luvas: "Luvas" };
  const estados = { presente: "detectado", observando: "verificando ausência", inconclusivo: "inconclusivo", possivel_ausencia: "possível ausência" };
  pessoas.forEach((pessoa) => {
    const card = document.createElement("article");
    card.className = "pessoa";
    const titulo = document.createElement("h3");
    titulo.textContent = "Pessoa " + pessoa.id + " · " + (pessoa.situacao_rotulo || (pessoa.postura === "Em pe" ? "Em pé" : pessoa.postura || "Postura inconclusiva"));
    card.append(titulo);
    Object.entries(pessoa.epis).forEach(([item, estado]) => {
      const badge = document.createElement("span");
      badge.className = "badge item-" + estado;
      badge.textContent = nomes[item] + ": " + estados[estado];
      card.append(badge);
    });
    if (!Object.keys(pessoa.epis).length) {
      const texto = document.createElement("p");
      texto.className = "muted small";
      texto.textContent = "Nenhum EPI obrigatório selecionado.";
      card.append(texto);
    }
    const leitura = document.createElement("p");
    leitura.className = "muted small";
    const angulo = Number.isFinite(pessoa.postura_angulo)
      ? "Inclinação do tronco: " + pessoa.postura_angulo + "°. " : "";
    if (pessoa.situacao_motivo) {
      leitura.textContent = pessoa.situacao_motivo + (pessoa.emergencia ? " Verificação humana pendente." : "");
    } else if (!pessoa.postura) {
      leitura.textContent = angulo + (pessoa.postura_motivo || "Corpo sem visibilidade suficiente.");
    } else if (pessoa.postura === "Deitada") {
      leitura.textContent = angulo + (pessoa.queda_confirmada ? "Possível queda confirmada para alerta."
        : "Verificando possível queda: " + (pessoa.queda_quadros || 0) + "/3 quadros; "
          + (pessoa.queda_observada_segundos || 0) + "/" + pessoa.queda_confirmacao_segundos + " segundos.");
    } else {
      leitura.textContent = angulo + "Postura estimada pela imagem da câmera.";
    }
    card.append(leitura);
    area.append(card);
  });
}

function mostrarEventos(eventos) {
  const area = elemento("eventos");
  area.replaceChildren();
  if (!eventos.length) {
    const linha = area.insertRow();
    const celula = linha.insertCell();
    celula.colSpan = 4;
    celula.className = "muted";
    celula.textContent = "Nenhuma ocorrência registrada.";
    return;
  }
  eventos.forEach((evento) => {
    const linha = area.insertRow();
    linha.insertCell().textContent = evento.data;
    linha.insertCell().textContent = evento.motivo + (evento.confirmacao === 'verificacao_humana_pendente' ? ' · Verificação humana pendente.' : '');
    const imagem = linha.insertCell();
    if (evento.arquivo) {
      const link = document.createElement("a");
      link.href = "/capturas/" + encodeURIComponent(evento.arquivo);
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Ver imagem";
      imagem.append(link);
    } else imagem.textContent = "Imagem desativada";
    linha.insertCell().textContent = evento.email;
  });
}

async function atualizarStatus() {
  const status = await requisitar("/status");
  ultimoStatus = status;
  elemento("estado").textContent = status.estado.toUpperCase();
  elemento("estado").className = "badge " + status.estado;
  elemento("mensagem").textContent = status.mensagem + (status.aviso ? " " + status.aviso : "")
    + (status.aviso_desempenho ? " " + status.aviso_desempenho : "");
  elemento("camera").textContent = status.camera;
  elemento("fps").textContent = status.fps;
  elemento("imagemEstado").textContent = status.executando ? "Monitoramento em andamento" : "Monitoramento parado";
  elemento("epiStatus").textContent = status.epi_ativo
    ? "Detector disponível para: " + status.epis_suportados.join(", ") + "."
    : status.epi_erro || (status.modelo_epi_disponivel ? "O detector será carregado ao iniciar." : "Modelo de EPI não encontrado; verificação inconclusiva.");
  if (status.epi_ativo) {
    const naoSuportados = status.epi_obrigatorio.filter((item) => !status.epis_suportados.includes(item));
    if (naoSuportados.length) elemento("epiStatus").textContent += " Sem suporte para: " + naoSuportados.join(", ") + ".";
  }
  if (status.epi_obrigatorio.includes("oculos")) {
    if (status.oculos_ativo) elemento("epiStatus").textContent += " Óculos: verificação adicional ativa.";
    if (status.oculos_erro) elemento("epiStatus").textContent += " " + status.oculos_erro;
    elemento("epiStatus").textContent += " Perfil ou evidência fraca de óculos deixam a leitura inconclusiva.";
  }
  if (!politicaCarregada) {
    document.querySelectorAll('input[name="epi"]').forEach((input) => { input.checked = status.epi_obrigatorio.includes(input.value); });
    elemento("confirmacao").value = status.confirmacao_segundos;
    politicaCarregada = true;
  }
  mostrarPessoas(status.deteccoes);
  mostrarEventos(status.eventos);
  atualizarBotoes();
}

async function atualizarAmostras() {
  const dados = await requisitar("/amostras");
  elemento("totalAmostras").textContent = dados.total + " amostra" + (dados.total === 1 ? "" : "s");
  elemento("amostras").replaceChildren();
  dados.amostras.forEach((amostra) => {
    const link = document.createElement("a");
    link.href = amostra.url;
    link.target = "_blank";
    link.rel = "noopener";
    const imagem = document.createElement("img");
    imagem.src = amostra.url;
    imagem.alt = "Amostra original pendente de anotação";
    imagem.loading = "lazy";
    link.append(imagem, document.createTextNode(amostra.arquivo));
    elemento("amostras").append(link);
  });
}

async function acao(url, dados) {
  if (ocupado) return;
  ocupado = true;
  atualizarBotoes();
  try {
    const resposta = await requisitar(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(dados || {})
    });
    feedback(resposta.mensagem);
    if (url === "/configurar-epi") politicaCarregada = false;
    if (url === "/coletar-amostra") await atualizarAmostras();
    await atualizarStatus();
  } catch (erro) {
    feedback(erro.message || "Não foi possível completar a solicitação.", true);
  } finally {
    ocupado = false;
    atualizarBotoes();
  }
}

async function cicloStatus() {
  try {
    await atualizarStatus();
  } catch (erro) {
    ultimoStatus = null;
    elemento("estado").textContent = "SEM CONEXÃO";
    atualizarBotoes();
    feedback("Falha ao consultar o sistema: " + erro.message, true);
  }
  setTimeout(cicloStatus, 1500);
}

async function cicloImagem() {
  if (ultimoStatus && ultimoStatus.executando && ultimoStatus.imagem_disponivel) {
    const controle = new AbortController();
    const limite = setTimeout(() => controle.abort(), 5000);
    try {
      const resposta = await fetch("/frame.jpg", { cache: "no-store", signal: controle.signal });
      if (resposta.status === 200) {
        const novaUrl = URL.createObjectURL(await resposta.blob());
        elemento("imagemCamera").src = novaUrl;
        elemento("imagemCamera").hidden = false;
        elemento("imagemEspera").hidden = true;
        if (urlImagem) URL.revokeObjectURL(urlImagem);
        urlImagem = novaUrl;
      }
    } catch (_) {
      elemento("imagemEstado").textContent = "Aguardando imagem da câmera";
    } finally {
      clearTimeout(limite);
    }
  }
  setTimeout(cicloImagem, 350);
}

elemento("iniciar").addEventListener("click", () => acao("/start"));
elemento("parar").addEventListener("click", () => acao("/stop"));
elemento("formEpi").addEventListener("submit", (evento) => {
  evento.preventDefault();
  acao("/configurar-epi", {
    obrigatorios: Array.from(document.querySelectorAll('input[name="epi"]:checked'), (input) => input.value),
    confirmacao_segundos: Number(elemento("confirmacao").value)
  });
});
elemento("formColeta").addEventListener("submit", (evento) => {
  evento.preventDefault();
  acao("/coletar-amostra", { observacao: elemento("observacao").value });
});
cicloStatus();
cicloImagem();
atualizarAmostras().catch((erro) => feedback(erro.message, true));
