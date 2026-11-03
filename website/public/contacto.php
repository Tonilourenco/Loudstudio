<?php
/**
 * Loudstudio — contact form handler.
 *
 * Receives the forms on /contactos/ and /es/li-lac/ and emails them to
 * info@loudstudio.com with PHP mail() (works on Hostinger without SMTP set-up).
 * Answers JSON to the page's JavaScript, or redirects back with ?enviado=1|0
 * when the browser sent the form without JavaScript.
 *
 * Spam protection: hidden "website" field, minimum time on page, and at most
 * RATE_LIMIT messages per IP address per hour.
 */

declare(strict_types=1);

const MAIL_TO = 'info@loudstudio.com';
const MAIL_FROM = 'info@loudstudio.com';
const RATE_LIMIT = 5;
const MIN_SECONDS = 3;
const RETURN_PAGES = ['/contactos/', '/li-lac/', '/es/li-lac/'];

const SUBJECTS = [
    'estudio' => 'Estúdio',
    'lilac' => 'Pro Audio · Li.LAC: pedido de orçamento',
    'outro' => 'Outro assunto',
];

const MESSAGES = [
    'pt' => [
        'method' => 'Pedido inválido.',
        'invalid' => 'Verifique os campos obrigatórios: nome, um email válido, mensagem (mínimo 10 caracteres) e a autorização.',
        'rate' => 'Recebemos várias mensagens deste endereço. Tente mais tarde ou escreva para info@loudstudio.com.',
        'failed' => 'Não foi possível enviar a mensagem. Tente de novo ou escreva para info@loudstudio.com.',
    ],
    'es' => [
        'method' => 'Solicitud no válida.',
        'invalid' => 'Revise los campos obligatorios: nombre, un email válido, mensaje (mínimo 10 caracteres) y la autorización.',
        'rate' => 'Hemos recibido varios mensajes desde esta dirección. Inténtelo más tarde o escriba a info@loudstudio.com.',
        'failed' => 'No se ha podido enviar el mensaje. Inténtelo de nuevo o escriba a info@loudstudio.com.',
    ],
];

header('X-Robots-Tag: noindex');
header('Cache-Control: no-store');

$wantsJson = stripos($_SERVER['HTTP_ACCEPT'] ?? '', 'application/json') !== false;
$lang = (($_POST['lang'] ?? '') === 'es') ? 'es' : 'pt';
$returnTo = in_array($_POST['origem'] ?? '', RETURN_PAGES, true) ? $_POST['origem'] : '/contactos/';

function finish(bool $ok, string $message = '', int $status = 200): void
{
    global $wantsJson, $returnTo;
    if ($wantsJson) {
        http_response_code($ok ? 200 : $status);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['ok' => $ok, 'message' => $message], JSON_UNESCAPED_UNICODE);
    } else {
        header('Location: ' . $returnTo . '?enviado=' . ($ok ? '1' : '0') . '#formulario', true, 303);
    }
    exit;
}

/** Text from a form field: trimmed, no control characters except newlines in long text. */
function field(string $name, int $max, bool $multiline = false): string
{
    $value = (string) ($_POST[$name] ?? '');
    $value = $multiline
        ? preg_replace('/[^\P{C}\n\t]/u', '', str_replace("\r\n", "\n", $value))
        : preg_replace('/\p{C}/u', ' ', $value);
    return mb_substr(trim((string) $value), 0, $max);
}

/** Display name for a From/Reply-To header: quoted ASCII, or an RFC 2047 encoded word. */
function display_name(string $name): string
{
    return preg_match('/^[\x20-\x7E]*$/', $name)
        ? '"' . addcslashes($name, '"\\') . '"'
        : mb_encode_mimeheader($name, 'UTF-8');
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    finish(false, MESSAGES[$lang]['method'], 405);
}

// Bots fill the hidden field or submit instantly. Pretend all went well.
// "t" is the time on the page in seconds, set by the page's JavaScript
// (empty when JavaScript is off, then only the hidden field is checked).
$elapsed = ctype_digit((string) ($_POST['t'] ?? '')) ? (int) $_POST['t'] : null;
if (($_POST['website'] ?? '') !== '' || ($elapsed !== null && $elapsed < MIN_SECONDS)) {
    finish(true);
}

$name = field('nome', 120);
$email = field('email', 160);
$phone = field('telefone', 40);
$topic = array_key_exists($_POST['assunto'] ?? '', SUBJECTS) ? $_POST['assunto'] : 'outro';
$message = field('mensagem', 5000, true);
$consent = ($_POST['consentimento'] ?? '') === '1';

if ($name === '' || !filter_var($email, FILTER_VALIDATE_EMAIL) || mb_strlen($message) < 10 || !$consent) {
    finish(false, MESSAGES[$lang]['invalid'], 422);
}

// Rate limit per IP address (stored as a hash, never the address itself).
$ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
$bucket = sys_get_temp_dir() . '/loudstudio-form-' . hash('sha256', $ip . __FILE__);
$recent = [];
if (is_readable($bucket)) {
    $recent = array_filter(
        array_map('intval', explode("\n", (string) file_get_contents($bucket))),
        static fn (int $ts): bool => $ts > time() - 3600
    );
}
if (count($recent) >= RATE_LIMIT) {
    finish(false, MESSAGES[$lang]['rate'], 429);
}

$subject = '[loudstudio.com] ' . SUBJECTS[$topic] . ' — ' . $name;
$body = implode("\n", [
    'Nova mensagem do formulário de loudstudio.com' . $returnTo . ($lang === 'es' ? ' (espanhol)' : ''),
    '',
    'Nome:     ' . $name,
    'Email:    ' . $email,
    'Telefone: ' . ($phone !== '' ? $phone : '—'),
    'Assunto:  ' . SUBJECTS[$topic],
    '',
    $message,
    '',
    '—',
    'Enviado em ' . date('Y-m-d H:i') . '. Responder a este email responde diretamente a ' . $email . '.',
]);

$headers = implode("\r\n", [
    'From: ' . mb_encode_mimeheader('Site Loudstudio', 'UTF-8') . ' <' . MAIL_FROM . '>',
    'Reply-To: ' . display_name($name) . ' <' . $email . '>',
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: 8bit',
    'X-Mailer: loudstudio-contact',
]);

$dryRun = getenv('LOUDSTUDIO_MAIL_DRYRUN');
if ($dryRun) {
    // Local testing: write the email to a file instead of sending it.
    $sent = file_put_contents($dryRun, "To: " . MAIL_TO . "\r\nSubject: $subject\r\n$headers\r\n\r\n$body\r\n", FILE_APPEND) !== false;
} else {
    $sent = mail(MAIL_TO, mb_encode_mimeheader($subject, 'UTF-8'), $body, $headers, '-f' . MAIL_FROM);
}

if (!$sent) {
    error_log('loudstudio contact form: mail() failed');
    finish(false, MESSAGES[$lang]['failed'], 500);
}

$recent[] = time();
@file_put_contents($bucket, implode("\n", $recent), LOCK_EX);
finish(true);
