// Executa o controlador real com DOM mínimo e HTTP no servidor simulado.
// Preparação: .\.venv\Scripts\python.exe tests/servidor_demo.py
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";
import { setTimeout as esperar } from "node:timers/promises";

class Elemento {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.textContent = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.checked = false;
    this.handlers = new Map();
    this.classList = {
      toggle: (nome, ativa) => {
        const classes = new Set(this.className.split(" ").filter(Boolean));
        ativa ? classes.add(nome) : classes.delete(nome);
        this.className = [...classes].join(" ");
      }
    };
  }
  append(...filhos) { this.children.push(...filhos); }
  replaceChildren(...filhos) { this.children = [...filhos]; }
  insertRow() { const linha = new Elemento("tr"); this.append(linha); return linha; }
  insertCell() { const celula = new Elemento("td"); this.append(celula); return celula; }
  addEventListener(evento, handler) { this.handlers.set(evento, handler); }
}

test("controles, confirmação por pessoa e coleta usando o JavaScript do painel", async () => {
  const html = await readFile(new URL("../templates/index.html", import.meta.url), "utf8");
  const js = await readFile(new URL("../static/painel.js", import.meta.url), "utf8");
  const elementos = new Map([...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Elemento()]));
  const checkboxes = ["capacete", "colete", "oculos", "luvas", "mascara"].map((nome) => {
    const input = new Elemento("input"); input.value = nome; return input;
  });
  const chamadas = [];
  const document = {
    getElementById: (id) => elementos.get(id) || null,
    createElement: (tag) => new Elemento(tag),
    createTextNode: (texto) => ({ textContent: texto }),
    querySelectorAll: (seletor) => seletor.endsWith(":checked")
      ? checkboxes.filter((input) => input.checked) : checkboxes,
  };
  const contexto = vm.createContext({
    document, console, URL, AbortController,
    setTimeout: () => 1, clearTimeout: () => {},
    fetch: async (url, opcoes) => {
      chamadas.push(url);
      return fetch("http://127.0.0.1:5001" + url, opcoes);
    },
  });
  vm.runInContext(js, contexto, { filename: "painel.js" });
  const executar = (codigo) => vm.runInContext(codigo, contexto);
  const aguardarStatus = async (condicao) => {
    const limite = Date.now() + 10000;
    do {
      await executar("atualizarStatus()");
      if (condicao()) return;
      await esperar(100);
    } while (Date.now() < limite);
    assert.fail("O estado esperado do painel não chegou em 10 segundos.");
  };
  await esperar(200);
  await executar("atualizarStatus()");
  assert.equal(elementos.get("estado").textContent, "PARADO");
  assert.equal(elementos.get("iniciar").disabled, false);
  assert.equal(elementos.get("coletar").disabled, true);
  assert.equal(elementos.get("formEpi").handlers.has("submit"), true);
  assert.equal(elementos.get("formColeta").handlers.has("submit"), true);
  await executar("acao('/configurar-epi', {obrigatorios:['capacete'],confirmacao_segundos:3})");
  assert.equal(checkboxes[0].checked, true);
  assert.match(elementos.get("feedback").textContent, /salva/);

  try {
    await executar("acao('/start')");
    // A primeira codificação JPEG pode levar mais de 200 ms em outro PC.
    await aguardarStatus(() => elementos.get("estado").textContent === "ATIVO"
      && !elementos.get("coletar").disabled);
    assert.equal(elementos.get("estado").textContent, "ATIVO");
    assert.equal(elementos.get("iniciar").disabled, true);
    assert.equal(elementos.get("parar").disabled, false);
    assert.equal(elementos.get("coletar").disabled, false);
    assert.equal(elementos.get("pessoas").children.length, 1);
    assert.match(elementos.get("pessoas").children[0].children[1].textContent, /verificando/);
    await executar("cicloImagem()");
    assert.equal(elementos.get("imagemCamera").hidden, false);
    assert.match(elementos.get("imagemCamera").src, /^blob:/);

    await aguardarStatus(() => elementos.get("pessoas").children[0]?.children[1]
      ?.textContent.includes("possível ausência")
      && elementos.get("eventos").children[0]?.children[3]?.textContent.includes("sem envio"));
    assert.match(elementos.get("pessoas").children[0].children[1].textContent, /possível ausência/);
    assert.equal(elementos.get("eventos").children.length, 1);
    assert.match(elementos.get("eventos").children[0].children[3].textContent, /sem envio/);

    await executar("acao('/coletar-amostra', {observacao:'Teste automatizado; câmera simulada'})");
    assert.match(elementos.get("feedback").textContent, /original salva/);
    assert.match(elementos.get("totalAmostras").textContent, /1 amostra/);
    assert.equal(elementos.get("amostras").children.length, 1);
    assert.equal(chamadas.includes("/stream"), false);
  } finally {
    await executar("acao('/stop')");
    await aguardarStatus(() => elementos.get("estado").textContent === "PARADO");
  }
  assert.equal(elementos.get("estado").textContent, "PARADO");
  assert.equal(elementos.get("iniciar").disabled, false);
  assert.equal(elementos.get("coletar").disabled, true);
  await executar("acao('/coletar-amostra', {})");
  assert.match(elementos.get("feedback").textContent, /Inicie a câmera/);
  assert.match(elementos.get("feedback").className, /erro/);
  executar("mostrarPessoas([{id:9,postura:'Deitada',postura_angulo:75,epis:{},queda_confirmada:false,queda_quadros:2,queda_observada_segundos:1,queda_confirmacao_segundos:2}])");
  let card = elementos.get("pessoas").children[0];
  assert.match(card.children[0].textContent, /Deitada/);
  assert.match(card.children.at(-1).textContent, /75°.*2\/3 quadros.*1\/2 segundos/);
  executar("mostrarPessoas([{id:9,postura:null,postura_angulo:null,postura_motivo:'Ombros sem visibilidade suficiente.',epis:{}}])");
  card = elementos.get("pessoas").children[0];
  assert.match(card.children[0].textContent, /Postura inconclusiva/);
  assert.match(card.children.at(-1).textContent, /Ombros sem visibilidade/);
});
