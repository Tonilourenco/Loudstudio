# Site loudstudio.com

Site novo da Loudstudio: HTML estático, um pouco de CSS e JavaScript, e um
único ficheiro PHP para o formulário de contacto. Sem WordPress, sem plugins,
sem base de dados, sem cookies.

```
website/
  public/            ← o site tal como vai para o servidor (public_html)
    index.html, estudio/, li-lac/, contactos/, privacidade/, es/li-lac/, 404.html
    contacto.php     ← envia o formulário para info@loudstudio.com
    .htaccess        ← HTTPS, cache, segurança, redirecionamentos do site antigo
    assets/          ← css, js, fontes, imagens, PDF da ficha técnica
  src/               ← onde se editam as páginas
    layout.html      ← <head> comum a todas as páginas
    header.pt.html, footer.pt.html, header.es.html, footer.es.html
    pages/           ← conteúdo de cada página
  tools/
    build.py         ← junta src/ e escreve as páginas em public/
    check_site.py    ← verifica links, imagens, âncoras e títulos
    fetch_assets.py  ← descarrega imagens e PDF do site antigo e otimiza-os
    make_og.py       ← gera as imagens de partilha (Facebook, WhatsApp…)
```

## Editar um texto

1. Abrir a página em `src/pages/` (por exemplo `src/pages/li-lac/index.html`).
   O bloco `<!--meta ... -->` no topo tem o título e a descrição para o Google.
2. Menu e rodapé estão em `src/header.pt.html` e `src/footer.pt.html`
   (versão espanhola: `*.es.html`).
3. Gerar as páginas e verificar:

   ```sh
   python3 website/tools/build.py
   python3 website/tools/check_site.py
   ```

Não editar diretamente os `.html` de `public/`: são gerados pelo `build.py` a
partir de `src/` e seriam reescritos. O GitHub verifica isto automaticamente
(workflow **Website check**).

## Ver o site no computador

```sh
cd website/public
python3 -m http.server 8080          # http://localhost:8080
```

Para testar também o formulário (sem enviar emails de verdade):

```sh
LOUDSTUDIO_MAIL_DRYRUN=/tmp/mail.txt php -S localhost:8090 -t website/public
```

As mensagens ficam escritas em `/tmp/mail.txt`.

## Imagens

As fotos vieram do WordPress antigo (`wp-content/uploads/2021/10/`) através do
`tools/fetch_assets.py`, que corre no GitHub (workflow **Website assets**) quando
`tools/assets.json` muda. Para acrescentar uma foto: pô-la acessível num URL,
acrescentá-la a `assets.json`, e o workflow gera as versões WebP e faz commit.
Também se pode simplesmente gravar um `.webp` em `public/assets/img/`.

Para pôr trabalhos do estúdio, há uma secção pronta mas comentada em
`src/pages/estudio/index.html` ("Trabalhos").

## Publicar na Hostinger

O WordPress atual fica online até o site novo ser aprovado.

### Antes de tudo: o domínio não está a resolver

Em 08/10/2026 o `loudstudio.com` **não tinha endereço IP público**: os
nameservers apontam para a Hostinger, mas o registo `ALIAS @ → loudstudio.com.cdn.hstgr.net`
não devolve IP e o CDN da Hostinger não tem certificado HTTPS para o domínio.
No hPanel, nas definições do site loudstudio.com, rever o CDN (desativar e
voltar a ativar, ou desligá-lo) e confirmar na zona DNS que `@` e `www` passam
a resolver para um IP; se não, pedir ao apoio da Hostinger que corrija o
registo `ALIAS` do CDN. Não mexer nos registos MX, SPF
(`TXT v=spf1`), DKIM (`hostingermail-*._domainkey`) e DMARC.

### Importante: backups expostos

A pasta `public_html/cpanel-backups/` tem o backup completo do alojamento antigo
(1,5 GB), o dump da base de dados e emails, e `public_html/cgi-bin.zip` tem 100 MB.
Tudo o que está em `public_html` pode ser descarregado pela web. Mover estas
pastas para fora de `public_html` (Gestor de Ficheiros → mover para a pasta
acima, `domains/loudstudio.com/`) o quanto antes. O `.htaccess` novo bloqueia
estes caminhos, mas o do WordPress atual não.

### 1. Pré-visualização (staging)

1. hPanel → **Domínios → Subdomínios**: criar `novo.loudstudio.com`
   com uma pasta própria (ex.: `public_html/novo`).
2. Gestor de Ficheiros: enviar o **conteúdo** de `website/public/` para essa pasta
   (incluindo o ficheiro oculto `.htaccess`). Mais simples: fazer um zip de
   `website/public`, enviá-lo e "Extrair".
3. Testar todas as páginas no telemóvel e enviar uma mensagem de teste pelo formulário.

### 2. Passagem para o site novo

1. Fazer backup do WordPress (hPanel → Ficheiros → Backups).
2. Mover o conteúdo atual de `public_html` (WordPress) para uma pasta fora de
   `public_html`, por exemplo `domains/loudstudio.com/wordpress-antigo/`.
3. Enviar o conteúdo de `website/public/` para `public_html`.
4. Confirmar: `https://loudstudio.com`, `/pro-audio/` (deve ir para `/li-lac/`),
   o formulário, e que `https://loudstudio.com/wp-login.php` dá 404.
5. Depois de umas semanas sem problemas, apagar a base de dados do WordPress no hPanel.

### Alternativa: publicação automática a partir do GitHub

O hPanel tem **Git → Implementação automática**. Como o repositório também tem
a app Desk Check, a forma limpa é publicar só a pasta `website/public` (por
exemplo num ramo próprio gerado por um workflow). Fica para uma fase seguinte.

## Notas técnicas

- **Formulário**: `contacto.php` usa `mail()` da Hostinger, remetente
  `info@loudstudio.com`, `Reply-To` com o email de quem escreve. Anti-spam:
  campo escondido, tempo mínimo de 3 s na página, máximo 5 mensagens por hora por IP.
- **Segurança**: o `.htaccess` define uma Content-Security-Policy restritiva. A
  única linha de JavaScript dentro do HTML (em `src/layout.html`) está autorizada
  pelo seu hash. Se essa linha mudar, recalcular o hash:
  `printf '%s' 'document.documentElement.classList.add("js")' | openssl dgst -sha256 -binary | base64`
  e atualizar `script-src` no `.htaccess`.
- **Fontes**: Archivo e Manrope (licença SIL OFL), alojadas no próprio site (sem
  Google Fonts, por causa do RGPD).
- **Mapa**: só carrega o Google Maps quando o visitante carrega em "Mostrar mapa".
- **Cores**: azul do logótipo `#00AEEF`; nas páginas Li.LAC, o violeta UV `#B06BFF`
  (cor da própria marca Li.LAC).

## Por confirmar

- Descrições dos serviços do estúdio (gravação, mistura, masterização, produção).
- "Técnico de som e produtor" e "30 anos de experiência" na apresentação do Toni.
- Link do Instagram (quando existir, acrescentar em `src/footer.*.html` e em
  `src/pages/contactos/index.html`).
- Lista "Para quem" na página Li.LAC.
- Ficha técnica em espanhol: o PDF atual é só em português.
