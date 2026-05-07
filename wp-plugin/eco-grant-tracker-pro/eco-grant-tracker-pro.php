<?php
/*
Plugin Name: EcoServants Grant Tracker Pro
Plugin URI: https://ecoservantsproject.org
Description: Advanced external-database grant tracker with proposal editor, funder preview, paginated grid, and live IRS 990 data proxy.
Version: 1.5.2
Author: EcoServants Project
Author URI: https://ecoservantsproject.org
*/

if (!defined('ABSPATH')) exit;

define('ESGT_PRO_PATH', plugin_dir_path(__FILE__));
define('ESGT_PRO_URL', plugin_dir_url(__FILE__));
define('ESGT_PRO_VERSION', '1.5.2');

require_once ESGT_PRO_PATH . 'includes/class-esgt-db.php';
require_once ESGT_PRO_PATH . 'includes/class-esgt-proposal.php';
require_once ESGT_PRO_PATH . 'includes/class-esgt-export.php';


/* ===============================================
   Admin Menu – Database Settings
=============================================== */
add_action('admin_menu', function(){
  add_options_page('Grant Tracker DB', 'Grant Tracker DB', 'manage_options', 'esgt-db-settings', 'esgt_db_settings_page');
  add_management_page('Grant Suggestions', 'Grant Suggestions', 'manage_options', 'esgt-grant-suggestions', 'esgt_suggestions_admin_page');
});

add_action('admin_init', function(){
  register_setting('esgt_db', 'esgt_db');
});

function esgt_encrypt($data){
  if(empty($data)) return '';
  $key = defined('AUTH_KEY') ? AUTH_KEY : 'ecoservants';
  $iv = substr(hash('sha256', $key), 0, 16);
  return base64_encode(openssl_encrypt($data, 'AES-256-CBC', $key, 0, $iv));
}
function esgt_decrypt($data){
  if(empty($data)) return '';
  $key = defined('AUTH_KEY') ? AUTH_KEY : 'ecoservants';
  $iv = substr(hash('sha256', $key), 0, 16);
  return openssl_decrypt(base64_decode($data), 'AES-256-CBC', $key, 0, $iv);
}


/* ===============================================
   Suggested Grants Table (WP DB)
=============================================== */
function esgt_suggestions_table_name() {
  global $wpdb;
  return $wpdb->prefix . 'grant_suggestions';
}

function esgt_install_suggestions_table() {
  global $wpdb;
  $table = esgt_suggestions_table_name();
  $charset_collate = $wpdb->get_charset_collate();

  require_once ABSPATH . 'wp-admin/includes/upgrade.php';

  $sql = "CREATE TABLE {$table} (
    id BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT(20) UNSIGNED NOT NULL,
    organization_name VARCHAR(255) NOT NULL,
    website_url TEXT NOT NULL,
    ein VARCHAR(9) NULL,
    state VARCHAR(50) NULL,
    contact_name VARCHAR(255) NULL,
    contact_email VARCHAR(255) NULL,
    rationale TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending_review',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by BIGINT(20) UNSIGNED NULL,
    reviewed_at DATETIME NULL,
    PRIMARY KEY  (id),
    KEY status (status),
    KEY user_id (user_id)
  ) {$charset_collate};";

  dbDelta($sql);
}

register_activation_hook(__FILE__, 'esgt_install_suggestions_table');

function esgt_maybe_install_suggestions_table() {
  global $wpdb;
  $table = esgt_suggestions_table_name();
  $exists = $wpdb->get_var($wpdb->prepare("SHOW TABLES LIKE %s", $table));
  if ($exists !== $table) {
    esgt_install_suggestions_table();
  }
}
add_action('init', 'esgt_maybe_install_suggestions_table');


function esgt_insert_suggestion($data) {
  global $wpdb;
  $table = esgt_suggestions_table_name();

  $defaults = [
    'user_id' => get_current_user_id(),
    'organization_name' => '',
    'website_url' => '',
    'ein' => null,
    'state' => null,
    'contact_name' => null,
    'contact_email' => null,
    'rationale' => '',
    'status' => 'pending_review'
  ];
  $data = array_merge($defaults, (array) $data);

  return $wpdb->insert($table, [
    'user_id' => (int) $data['user_id'],
    'organization_name' => $data['organization_name'],
    'website_url' => $data['website_url'],
    'ein' => $data['ein'],
    'state' => $data['state'],
    'contact_name' => $data['contact_name'],
    'contact_email' => $data['contact_email'],
    'rationale' => $data['rationale'],
    'status' => $data['status']
  ], [
    '%d','%s','%s','%s','%s','%s','%s','%s','%s'
  ]);
}

function esgt_db_settings_page(){
  $opts = get_option('esgt_db', []); ?>
  <div class="wrap">
    <h1>External Database Settings</h1>
    <form method="post" action="options.php">
      <?php settings_fields('esgt_db'); ?>
      <table class="form-table">
        <tr><th>Host</th><td><input type="text" name="esgt_db[host]" value="<?php echo esc_attr($opts['host'] ?? ''); ?>"></td></tr>
        <tr><th>Port</th><td><input type="text" name="esgt_db[port]" value="<?php echo esc_attr($opts['port'] ?? '3306'); ?>"></td></tr>
        <tr><th>Database</th><td><input type="text" name="esgt_db[name]" value="<?php echo esc_attr($opts['name'] ?? ''); ?>"></td></tr>
        <tr><th>User</th><td><input type="text" name="esgt_db[user]" value="<?php echo esc_attr($opts['user'] ?? ''); ?>"></td></tr>
        <tr><th>Password</th><td><input type="password" name="esgt_db[pass]" value="<?php echo esc_attr(esgt_decrypt($opts['pass'] ?? '')); ?>"></td></tr>
      </table>
      <?php submit_button('Save Settings'); ?>
    </form>
  </div>
  <?php
}


function esgt_suggestions_admin_page() {
  if (!current_user_can('manage_options')) return;

  // Export
  if (isset($_GET['esgt_export']) && $_GET['esgt_export'] === '1') {
    check_admin_referer('esgt_export_suggestions');
    esgt_export_suggestions_csv();
    exit;
  }

  // Status update
  if (isset($_POST['esgt_suggestion_action']) && $_POST['esgt_suggestion_action'] === 'update_status') {
    check_admin_referer('esgt_update_suggestion_status');
    $id = isset($_POST['id']) ? (int) $_POST['id'] : 0;
    $status = isset($_POST['status']) ? sanitize_text_field(wp_unslash($_POST['status'])) : 'pending_review';
    if ($id > 0) {
      global $wpdb;
      $table = esgt_suggestions_table_name();
      $wpdb->update($table, [
        'status' => $status,
        'reviewed_by' => get_current_user_id(),
        'reviewed_at' => current_time('mysql')
      ], ['id' => $id], ['%s','%d','%s'], ['%d']);
      echo '<div class="notice notice-success"><p>Status updated.</p></div>';
    }
  }

  global $wpdb;
  $table = esgt_suggestions_table_name();
  $rows = $wpdb->get_results("SELECT * FROM {$table} ORDER BY created_at DESC LIMIT 500", ARRAY_A);

  $export_url = wp_nonce_url(admin_url('tools.php?page=esgt-grant-suggestions&esgt_export=1'), 'esgt_export_suggestions');

  echo '<div class="wrap">';
  echo '<h1>Grant Suggestions</h1>';
  echo '<p><a class="button button-primary" href="' . esc_url($export_url) . '">Export CSV</a></p>';

  if (empty($rows)) {
    echo '<p>No suggestions yet.</p>';
    echo '</div>';
    return;
  }

  echo '<table class="widefat striped">';
  echo '<thead><tr>';
  echo '<th>ID</th><th>Organization</th><th>Website</th><th>EIN</th><th>State</th><th>Contact</th><th>Email</th><th>Status</th><th>Submitted</th><th>Action</th>';
  echo '</tr></thead><tbody>';

  $status_opts = ['pending_review' => 'Pending review', 'approved' => 'Approved', 'rejected' => 'Rejected', 'merged_existing' => 'Merged existing'];

  foreach ($rows as $r) {
    $id = (int) $r['id'];
    echo '<tr>';
    echo '<td>' . $id . '</td>';
    echo '<td><strong>' . esc_html($r['organization_name']) . '</strong><br><small>' . esc_html(wp_trim_words($r['rationale'], 18, '…')) . '</small></td>';
    echo '<td><a href="' . esc_url($r['website_url']) . '" target="_blank" rel="noopener">Visit</a></td>';
    echo '<td>' . esc_html($r['ein']) . '</td>';
    echo '<td>' . esc_html($r['state']) . '</td>';
    echo '<td>' . esc_html($r['contact_name']) . '</td>';
    echo '<td>' . esc_html($r['contact_email']) . '</td>';

    echo '<td>';
    echo '<form method="post" style="display:flex;gap:8px;align-items:center;">';
    wp_nonce_field('esgt_update_suggestion_status');
    echo '<input type="hidden" name="esgt_suggestion_action" value="update_status">';
    echo '<input type="hidden" name="id" value="' . $id . '">';
    echo '<select name="status">';
    foreach ($status_opts as $k => $label) {
      $sel = ($r['status'] === $k) ? ' selected' : '';
      echo '<option value="' . esc_attr($k) . '"' . $sel . '>' . esc_html($label) . '</option>';
    }
    echo '</select>';
    echo '</td>';

    echo '<td>' . esc_html($r['created_at']) . '</td>';
    echo '<td><button class="button">Save</button></td>';
    echo '</form>';
    echo '</tr>';
  }

  echo '</tbody></table>';
  echo '<p style="margin-top:12px;"><em>Showing the 500 most recent suggestions.</em></p>';
  echo '</div>';
}

function esgt_export_suggestions_csv() {
  if (!current_user_can('manage_options')) return;

  global $wpdb;
  $table = esgt_suggestions_table_name();
  $rows = $wpdb->get_results("SELECT * FROM {$table} ORDER BY created_at DESC", ARRAY_A);

  header('Content-Type: text/csv; charset=utf-8');
  header('Content-Disposition: attachment; filename=grant-suggestions-' . gmdate('Y-m-d') . '.csv');

  $out = fopen('php://output', 'w');
  fputcsv($out, ['id','user_id','organization_name','website_url','ein','state','contact_name','contact_email','rationale','status','created_at','reviewed_by','reviewed_at']);

  foreach ($rows as $r) {
    fputcsv($out, [
      $r['id'], $r['user_id'], $r['organization_name'], $r['website_url'], $r['ein'], $r['state'],
      $r['contact_name'], $r['contact_email'], $r['rationale'], $r['status'], $r['created_at'],
      $r['reviewed_by'], $r['reviewed_at']
    ]);
  }
  fclose($out);
}

/* ===============================================
   Enqueue Scripts & Styles
=============================================== */
add_action('admin_enqueue_scripts', function(){
  wp_enqueue_style('esgt-admin', ESGT_PRO_URL . 'assets/admin-modern.css');
});

add_action('wp_enqueue_scripts', function(){
  // Cache-busting: use file modification times so browsers/CDNs pull the latest assets.
  $js_path  = ESGT_PRO_PATH . 'assets/front.js';
  $css_path = ESGT_PRO_PATH . 'assets/admin-modern.css';
  $js_ver   = file_exists($js_path) ? (string) filemtime($js_path) : ESGT_PRO_VERSION;
  $css_ver  = file_exists($css_path) ? (string) filemtime($css_path) : ESGT_PRO_VERSION;

  wp_enqueue_script('esgt-front', ESGT_PRO_URL . 'assets/front.js', ['jquery'], $js_ver, true);
  wp_localize_script('esgt-front', 'ESGT', [
    'ajax_url' => admin_url('admin-ajax.php'),
    'nonce' => wp_create_nonce('esgt_nonce'),
    'statuses' => ['Researching','Planned','In Progress','Submitted','Awarded','Declined']
  ]);
  wp_enqueue_style('esgt-front-style', ESGT_PRO_URL . 'assets/admin-modern.css', [], $css_ver);
  // Removed TinyMCE/editor assets as proposal writing functionality has been deprecated
});

/* ===============================================
   Unified Shortcode [grant_tracker_pro]
   — Pagination + Proposal Editor + Modal Preview
=============================================== */
add_shortcode('grant_tracker_pro', function(){
  
  // Access gate: keep /grant-tracker/ public but restrict the shortcode output
  if (!is_user_logged_in()) {
    $login_url = wp_login_url(get_permalink());
    return '<div class="esa-gt-locked">'
      . '<h2>Intern access required</h2>'
      . '<p>Please log in to access the EcoServants Grant Academy.</p>'
      . '<p><a class="button" href="' . esc_url($login_url) . '">Log in</a></p>'
      . '</div>';
  }

  $user = wp_get_current_user();
  $is_intern = in_array('intern', (array) $user->roles, true);
  $is_admin  = current_user_can('manage_options');

  if (!$is_intern && !$is_admin) {
    return '<div class="esa-gt-locked">'
      . '<h2>Access restricted</h2>'
      . '<p>This workspace is reserved for EcoServants interns.</p>'
      . '</div>';
  }

$db = new ESGT_DB();

  $page = isset($_GET['pg']) ? max(1, intval($_GET['pg'])) : 1;
  $limit = 18;
  $offset = ($page - 1) * $limit;

  // Paginated query
  $pdo = new PDO(
    sprintf('mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4',
      get_option('esgt_db')['host'],
      get_option('esgt_db')['port'],
      get_option('esgt_db')['name']
    ),
    get_option('esgt_db')['user'],
    get_option('esgt_db')['pass']
  );
  // IMPORTANT: Offset pagination requires a deterministic ORDER BY.
  // If multiple rows share the same deadline (or deadline is NULL), MySQL may return them
  // in a different order between requests, which can cause duplicates across pages.
  // Use a stable tie-breaker (id) and push NULL deadlines to the end.
  // ==============================
// Filters (server-side)
// ==============================

$q_raw      = isset($_GET['q']) ? sanitize_text_field(wp_unslash($_GET['q'])) : '';
$status_raw = isset($_GET['status']) ? sanitize_text_field(wp_unslash($_GET['status'])) : '';
$ein_raw    = isset($_GET['ein']) ? preg_replace('/[^0-9]/', '', wp_unslash($_GET['ein'])) : '';

$mk_raw     = isset($_GET['mk']) ? sanitize_text_field(wp_unslash($_GET['mk'])) : '';
$mk_mode    = (isset($_GET['mk_mode']) && $_GET['mk_mode'] === 'all') ? 'all' : 'any';

$pak_raw    = isset($_GET['pak']) ? sanitize_text_field(wp_unslash($_GET['pak'])) : '';
$pak_mode   = (isset($_GET['pak_mode']) && $_GET['pak_mode'] === 'all') ? 'all' : 'any';

$gk_raw     = isset($_GET['gk']) ? sanitize_text_field(wp_unslash($_GET['gk'])) : '';
$gk_mode    = (isset($_GET['gk_mode']) && $_GET['gk_mode'] === 'all') ? 'all' : 'any';

$ftk_raw    = isset($_GET['ftk']) ? sanitize_text_field(wp_unslash($_GET['ftk'])) : '';
$ftk_mode   = (isset($_GET['ftk_mode']) && $_GET['ftk_mode'] === 'all') ? 'all' : 'any';

$exk_raw    = isset($_GET['exk']) ? sanitize_text_field(wp_unslash($_GET['exk'])) : '';
$exk_mode   = (isset($_GET['exk_mode']) && $_GET['exk_mode'] === 'all') ? 'all' : 'any';

$global_in_raw  = isset($_GET['global_in']) ? sanitize_text_field(wp_unslash($_GET['global_in'])) : '';
$global_in_mode = (isset($_GET['global_in_mode']) && $_GET['global_in_mode'] === 'all') ? 'all' : 'any';
$global_ex_raw  = isset($_GET['global_ex']) ? sanitize_text_field(wp_unslash($_GET['global_ex'])) : '';

$params = [];
$where  = [];

// Detect available columns so we don't hard-fail when enrichment columns aren't added yet
$cols = [];
try {
  $colStmt = $pdo->query("DESCRIBE grants");
  $cols = $colStmt ? $colStmt->fetchAll(PDO::FETCH_COLUMN, 0) : [];
} catch (Exception $e) {
  $cols = [];
}
$cols_map = [];
foreach ($cols as $c) { $cols_map[$c] = true; }
$has_col = function($c) use (&$cols_map){ return isset($cols_map[$c]); };

// Helpers
$esgt_split_terms = function($raw){
  $raw = trim((string)$raw);
  if ($raw === '') return [];
  $raw = str_replace(["\r\n", "\r"], "\n", $raw);
  $raw = str_replace([";", "|"], ",", $raw);
  $parts = preg_split('/[,\n]+/', $raw);
  $out = [];
  foreach ($parts as $p) {
    $t = trim($p);
    if ($t !== '') $out[] = $t;
  }
  // de-dupe, preserve order
  $seen = [];
  $uniq = [];
  foreach ($out as $t) {
    $k = strtolower($t);
    if (!isset($seen[$k])) { $seen[$k] = true; $uniq[] = $t; }
  }
  return $uniq;
};

$esgt_like_group = function($column, $terms, $mode, $prefix) use (&$params, $has_col){
  if (empty($terms)) return '';
  if (!$has_col($column)) return '';
  $clauses = [];
  $i = 0;
  foreach ($terms as $t) {
    $key = ':' . $prefix . '_' . $i;
    $params[$key] = '%' . $t . '%';
    $clauses[] = "COALESCE($column,'') LIKE $key";
    $i++;
  }
  $join = ($mode === 'all') ? ' AND ' : ' OR ';
  return '(' . implode($join, $clauses) . ')';
};


$esgt_expand_geo_terms = function($terms){
  if (empty($terms)) return $terms;

  // US states + DC mapping (name => abbreviation)
  $map = [
    'ALABAMA'=>'AL','ALASKA'=>'AK','ARIZONA'=>'AZ','ARKANSAS'=>'AR','CALIFORNIA'=>'CA','COLORADO'=>'CO','CONNECTICUT'=>'CT',
    'DELAWARE'=>'DE','DISTRICT OF COLUMBIA'=>'DC','FLORIDA'=>'FL','GEORGIA'=>'GA','HAWAII'=>'HI','IDAHO'=>'ID','ILLINOIS'=>'IL',
    'INDIANA'=>'IN','IOWA'=>'IA','KANSAS'=>'KS','KENTUCKY'=>'KY','LOUISIANA'=>'LA','MAINE'=>'ME','MARYLAND'=>'MD','MASSACHUSETTS'=>'MA',
    'MICHIGAN'=>'MI','MINNESOTA'=>'MN','MISSISSIPPI'=>'MS','MISSOURI'=>'MO','MONTANA'=>'MT','NEBRASKA'=>'NE','NEVADA'=>'NV',
    'NEW HAMPSHIRE'=>'NH','NEW JERSEY'=>'NJ','NEW MEXICO'=>'NM','NEW YORK'=>'NY','NORTH CAROLINA'=>'NC','NORTH DAKOTA'=>'ND','OHIO'=>'OH',
    'OKLAHOMA'=>'OK','OREGON'=>'OR','PENNSYLVANIA'=>'PA','RHODE ISLAND'=>'RI','SOUTH CAROLINA'=>'SC','SOUTH DAKOTA'=>'SD','TENNESSEE'=>'TN',
    'TEXAS'=>'TX','UTAH'=>'UT','VERMONT'=>'VT','VIRGINIA'=>'VA','WASHINGTON'=>'WA','WEST VIRGINIA'=>'WV','WISCONSIN'=>'WI','WYOMING'=>'WY'
  ];

  // reverse mapping (abbr => name)
  $rev = [];
  foreach ($map as $name => $abbr) { $rev[$abbr] = $name; }

  $out = [];
  $seen = [];

  foreach ($terms as $t) {
    $t_clean = trim((string)$t);
    if ($t_clean === '') continue;

    // Keep original term
    $candidates = [$t_clean];

    // Normalize token for matching
    $u = strtoupper($t_clean);
    $u = preg_replace('/\s+/', ' ', $u);

    // If user typed full state name, add abbreviation
    if (isset($map[$u])) {
      $candidates[] = $map[$u];
    }

    // If user typed 2-letter abbreviation, add full name
    if (preg_match('/^[A-Z]{2}$/', $u) && isset($rev[$u])) {
      $candidates[] = ucwords(strtolower($rev[$u]));
    }

    // Special cases users might type
    if ($u === 'D.C.' || $u === 'WASHINGTON DC' || $u === 'WASHINGTON, DC' || $u === 'WASHINGTON D.C.' || $u === 'WASHINGTON, D.C.') {
      $candidates[] = 'DC';
      $candidates[] = 'District of Columbia';
    }

    foreach ($candidates as $cand) {
      $k = strtolower($cand);
      if (!isset($seen[$k])) { $seen[$k] = true; $out[] = $cand; }
    }
  }

  return $out;
};

// Basic filters
// Treat legacy/placeholder statuses as part of the normal workflow.
// "Imported" (and blank/NULL) should behave like "Researching".
if ($status_raw !== '' && $has_col('status')) {
  if ($status_raw === 'Researching') {
    $where[] = "(COALESCE(status,'') = :status OR LOWER(COALESCE(status,'')) = 'imported' OR COALESCE(status,'') = '')";
    $params[':status'] = $status_raw;
  } else {
    $where[] = 'status = :status';
    $params[':status'] = $status_raw;
  }
}

if ($ein_raw !== '' && $has_col('ein')) {
  $where[] = 'REPLACE(REPLACE(REPLACE(COALESCE(ein,""),"-","")," ",""),".","") = :ein';
  $params[':ein'] = $ein_raw;
}

// Text search across common fields + keyword fields if present
if ($q_raw !== '') {
  $params[':q'] = '%' . $q_raw . '%';
  $searchCols = [];
  foreach (['funder','title','notes','website','address'] as $c) { if ($has_col($c)) $searchCols[] = $c; }
  foreach (['mission_keywords','program_area_keywords','geographic_focus_keywords','funding_type_keywords','exclusion_keywords'] as $c) { if ($has_col($c)) $searchCols[] = $c; }
  if (!empty($searchCols)) {
    $ors = [];
    foreach ($searchCols as $c) { $ors[] = "COALESCE($c,'') LIKE :q"; }
    $where[] = '(' . implode(' OR ', $ors) . ')';
  }
}

// Advanced keyword columns
$mk_terms  = $esgt_split_terms($mk_raw);
$pak_terms = $esgt_split_terms($pak_raw);
$gk_terms  = $esgt_expand_geo_terms($esgt_split_terms($gk_raw));
$ftk_terms = $esgt_split_terms($ftk_raw);
$exk_terms = $esgt_split_terms($exk_raw);

$mk_clause  = $esgt_like_group('mission_keywords', $mk_terms, $mk_mode, 'mk');
if ($mk_clause) $where[] = $mk_clause;

$pak_clause = $esgt_like_group('program_area_keywords', $pak_terms, $pak_mode, 'pak');
if ($pak_clause) $where[] = $pak_clause;

$gk_clause  = $esgt_like_group('geographic_focus_keywords', $gk_terms, $gk_mode, 'gk');
if ($gk_clause) $where[] = $gk_clause;

$ftk_clause = $esgt_like_group('funding_type_keywords', $ftk_terms, $ftk_mode, 'ftk');
if ($ftk_clause) $where[] = $ftk_clause;

$exk_clause = $esgt_like_group('exclusion_keywords', $exk_terms, $exk_mode, 'exk');
if ($exk_clause) $where[] = $exk_clause;

// Global include/exclude across keyword fields + core fields that exist
$global_targets = [];
foreach (['mission_keywords','program_area_keywords','geographic_focus_keywords','funding_type_keywords','exclusion_keywords','funder','title','notes'] as $c) {
  if ($has_col($c)) $global_targets[] = $c;
}

$global_in_terms = $esgt_split_terms($global_in_raw);
if (!empty($global_in_terms) && !empty($global_targets)) {
  $blocks = [];
  $i = 0;
  foreach ($global_in_terms as $t) {
    $key = ':global_in_' . $i;
    $params[$key] = '%' . $t . '%';
    $ors = [];
    foreach ($global_targets as $c) { $ors[] = "COALESCE($c,'') LIKE $key"; }
    $blocks[] = '(' . implode(' OR ', $ors) . ')';
    $i++;
  }
  $join = ($global_in_mode === 'all') ? ' AND ' : ' OR ';
  $where[] = '(' . implode($join, $blocks) . ')';
}

$global_ex_terms = $esgt_split_terms($global_ex_raw);
if (!empty($global_ex_terms) && !empty($global_targets)) {
  $blocks = [];
  $i = 0;
  foreach ($global_ex_terms as $t) {
    $key = ':global_ex_' . $i;
    $params[$key] = '%' . $t . '%';
    $ands = [];
    foreach ($global_targets as $c) { $ands[] = "COALESCE($c,'') NOT LIKE $key"; }
    $blocks[] = '(' . implode(' AND ', $ands) . ')';
    $i++;
  }
  $where[] = '(' . implode(' AND ', $blocks) . ')';
}

$where_sql = '';
if (!empty($where)) {
  $where_sql = ' WHERE ' . implode(' AND ', $where);
}

$sql = "SELECT * FROM grants" . $where_sql . " ORDER BY (deadline IS NULL) ASC, deadline ASC, id ASC LIMIT :limit OFFSET :offset";
$stmt = $pdo->prepare($sql);
foreach ($params as $k => $v) {
  $stmt->bindValue($k, $v, PDO::PARAM_STR);
}
$stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
$stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
$stmt->execute();
$grants = $stmt->fetchAll(PDO::FETCH_ASSOC);

$countSql = "SELECT COUNT(*) FROM grants" . $where_sql;
$countStmt = $pdo->prepare($countSql);
foreach ($params as $k => $v) {
  $countStmt->bindValue($k, $v, PDO::PARAM_STR);
}
$countStmt->execute();
$total = (int)$countStmt->fetchColumn();
$totalPages = (int)ceil($total / $limit);

ob_start();
 ?>

  <?php
    $current_user = wp_get_current_user();
    $is_logged_in = is_user_logged_in();
    $display_name = $is_logged_in ? ($current_user->display_name ?: $current_user->user_login) : '';
    $logout_url   = wp_logout_url(home_url('/'));
  ?>

  <div class="esa-gt-hero">
    <div class="esa-gt-hero__inner">
      <div class="esa-gt-hero__left">
        <div class="esa-gt-kicker">EcoServants® Academy</div>
        <h1 class="esa-gt-title">Grant Workspace</h1>
        <div class="esa-gt-subtitle">Your intern workspace for tracking funders, drafting proposals, and moving grants forward</div>

        <div class="esa-gt-stats">
          <div class="esa-gt-stat">
            <div class="esa-gt-stat__label">Total Grants</div>
            <div class="esa-gt-stat__value"><?php echo number_format((int)$total); ?></div>
          </div>
          <div class="esa-gt-stat">
            <div class="esa-gt-stat__label">Showing</div>
            <div class="esa-gt-stat__value"><?php echo number_format((int)count($grants)); ?></div>
          </div>
          <div class="esa-gt-stat">
            <div class="esa-gt-stat__label">Page</div>
            <div class="esa-gt-stat__value"><?php echo (int)$page; ?> / <?php echo (int)$totalPages; ?></div>
          </div>
        </div>
      </div>

      <div class="esa-gt-hero__right">
        <?php if ($is_logged_in): ?>
          <div class="esa-gt-usercard">
            <div class="esa-gt-usercard__name"><?php echo esc_html($display_name); ?></div>
            <div class="esa-gt-usercard__meta">Logged in</div>
            <a class="esa-gt-btn esa-gt-btn--ghost" href="<?php echo esc_url($logout_url); ?>">Logout</a>
            <button type="button" class="esa-gt-btn" id="esgt-open-suggest">Suggest Grant</button>
          </div>
        <?php endif; ?>
      </div>
    </div>
  </div>
<div class="esgt-toolbar">
  <form class="esgt-filter-form" method="get" action="">
    <input type="hidden" name="pg" value="1">

    <input
      type="search"
      class="esgt-search"
      name="q"
      value="<?php echo esc_attr($q_raw); ?>"
      placeholder="Search funders or keywords"
      aria-label="Search"
    >

    <select class="esgt-status-filter" name="status" aria-label="Status">
      <option value="" <?php selected($status_raw, ''); ?>>All Statuses</option>
      <option value="Researching" <?php selected($status_raw, 'Researching'); ?>>Researching</option>
      <option value="Planned" <?php selected($status_raw, 'Planned'); ?>>Planned</option>
      <option value="In Progress" <?php selected($status_raw, 'In Progress'); ?>>In Progress</option>
      <option value="Submitted" <?php selected($status_raw, 'Submitted'); ?>>Submitted</option>
      <option value="Awarded" <?php selected($status_raw, 'Awarded'); ?>>Awarded</option>
      <option value="Declined" <?php selected($status_raw, 'Declined'); ?>>Declined</option>
    </select>

    <input
      type="text"
      class="esgt-ein"
      name="ein"
      inputmode="numeric"
      autocomplete="off"
      placeholder="EIN (digits only)"
      maxlength="12"
      aria-label="EIN"
      value="<?php echo esc_attr($ein_raw); ?>"
    >

    <button type="button" class="esgt-btn esgt-advanced-toggle" aria-expanded="false">Advanced Filters</button>
    <button type="submit" class="esgt-btn esgt-apply-filters">Apply</button>

    <a class="esgt-btn esgt-clear-filters" href="<?php echo esc_url(remove_query_arg(array('q','status','ein','mk','mk_mode','pak','pak_mode','gk','gk_mode','ftk','ftk_mode','exk','exk_mode','global_in','global_in_mode','global_ex','pg'))); ?>">Clear</a>

    <a href="#" class="esgt-btn esgt-ein-propublica" data-action="propublica">ProPublica</a>

    <div class="esgt-active-filters" aria-label="Active filters" aria-live="polite" hidden></div>

    <div class="esgt-advanced-panel" hidden>

      <div class="esgt-adv-helpbar">
        <button type="button" class="esgt-help-toggle" aria-expanded="false" aria-controls="esgt-adv-instructions">
          <span class="esgt-help-star" aria-hidden="true">★</span>
          Advanced Filter Instructions
        </button>
        <div id="esgt-adv-instructions" class="esgt-help-box" hidden>
          <div><strong>Comma-separated.</strong></div>
          <div><strong>Any</strong> = match any input entry.</div>
          <div><strong>All</strong> = match every term.</div>
          <div><strong>Global include</strong> = broad search across fields.</div>
        </div>
      </div>

      <div class="esgt-adv-grid">

        <div class="esgt-adv-field">
          <label>Mission keywords</label>
          <div class="esgt-adv-row">
            <select name="mk_mode" aria-label="Mission match mode">
              <option value="any" <?php selected($mk_mode, 'any'); ?>>Any</option>
              <option value="all" <?php selected($mk_mode, 'all'); ?>>All</option>
            </select>
            <input type="text" name="mk" value="<?php echo esc_attr($mk_raw); ?>" placeholder="watershed, youth, cleanup">
          </div>
        </div>

        <div class="esgt-adv-field">
          <label>Program area keywords</label>
          <div class="esgt-adv-row">
            <select name="pak_mode" aria-label="Program area match mode">
              <option value="any" <?php selected($pak_mode, 'any'); ?>>Any</option>
              <option value="all" <?php selected($pak_mode, 'all'); ?>>All</option>
            </select>
            <input type="text" name="pak" value="<?php echo esc_attr($pak_raw); ?>" placeholder="education, conservation, restoration">
          </div>
        </div>

        <div class="esgt-adv-field">
          <label>Geographic focus keywords</label>
          <div class="esgt-adv-row">
            <select name="gk_mode" aria-label="Geographic match mode">
              <option value="any" <?php selected($gk_mode, 'any'); ?>>Any</option>
              <option value="all" <?php selected($gk_mode, 'all'); ?>>All</option>
            </select>
            <input type="text" name="gk" value="<?php echo esc_attr($gk_raw); ?>" placeholder="San Diego, California, Southwest">
          </div>
        </div>

        <div class="esgt-adv-field">
          <label>Funding type keywords</label>
          <div class="esgt-adv-row">
            <select name="ftk_mode" aria-label="Funding type match mode">
              <option value="any" <?php selected($ftk_mode, 'any'); ?>>Any</option>
              <option value="all" <?php selected($ftk_mode, 'all'); ?>>All</option>
            </select>
            <input type="text" name="ftk" value="<?php echo esc_attr($ftk_raw); ?>" placeholder="general operating, capital, program">
          </div>
        </div>

        <div class="esgt-adv-field">
          <label>Exclusion keywords</label>
          <div class="esgt-adv-row">
            <select name="exk_mode" aria-label="Exclusion match mode">
              <option value="any" <?php selected($exk_mode, 'any'); ?>>Any</option>
              <option value="all" <?php selected($exk_mode, 'all'); ?>>All</option>
            </select>
            <input type="text" name="exk" value="<?php echo esc_attr($exk_raw); ?>" placeholder="religious, political, individual">
          </div>
        </div>

        <div class="esgt-adv-field">
          <label>Global include <span class="esgt-scope-badge">Across all fields</span></label>
          <div class="esgt-adv-row">
            <select name="global_in_mode" aria-label="Global include match mode">
              <option value="any" <?php selected($global_in_mode, 'any'); ?>>Any</option>
              <option value="all" <?php selected($global_in_mode, 'all'); ?>>All</option>
            </select>
            <input type="text" name="global_in" value="<?php echo esc_attr($global_in_raw); ?>" placeholder="stormwater, river, volunteer">
          </div>
        </div>

        <div class="esgt-adv-field">
          <label>Global exclude <span class="esgt-scope-badge">Across all fields</span></label>
          <input type="text" name="global_ex" value="<?php echo esc_attr($global_ex_raw); ?>" placeholder="clinical trials, healthcare">
        </div>

      </div>
    </div>

    <style>
      .esgt-adv-helpbar{display:flex;flex-direction:column;gap:10px;margin:0 0 12px 0;}
      .esgt-help-toggle{display:inline-flex;align-items:center;gap:8px;border:1px solid #243b7e;background:#f5f7ff;color:#243b7e;border-radius:10px;padding:6px 10px;font-weight:600;cursor:pointer;}
      .esgt-help-toggle:focus{outline:2px solid #243b7e;outline-offset:2px;}
      .esgt-help-star{font-size:14px;line-height:1;}
      .esgt-help-box{border:1px solid #d6def7;background:#fbfcff;border-radius:12px;padding:10px 12px;color:#1f2a44;max-width:620px;}
      .esgt-help-box div{margin:2px 0;}
    </style>

    <script>
      (function(){
        function qs(sel, root){return (root||document).querySelector(sel);}
        function setExpanded(btn, box, expanded){
          btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
          if (expanded) { box.removeAttribute('hidden'); } else { box.setAttribute('hidden',''); }
        }

        document.addEventListener('click', function(e){
          var btn = e.target.closest && e.target.closest('.esgt-help-toggle');
          if (!btn) return;
          e.preventDefault();
          var box = qs('#esgt-adv-instructions');
          if (!box) return;
          var isOpen = btn.getAttribute('aria-expanded') === 'true';
          setExpanded(btn, box, !isOpen);
        });
      })();
    </script>

  </form>
</div>

<div class="esgt-grant-grid">
    <?php foreach($grants as $g): ?>
      <?php
        $raw_status = (string)($g['status'] ?? '');
        $raw_status_trim = trim($raw_status);
        $display_status = $raw_status_trim;
        if ($display_status === '' || strtolower($display_status) === 'imported') {
          $display_status = 'Researching';
        }
      ?>
      <div class="esgt-grant-card" data-id="<?php echo esc_attr($g['id']); ?>" data-proposal="<?php echo esc_attr($g['proposal'] ?? ''); ?>">
        <h3>
          <a href="#" class="esgt-funder-title" data-funder-url="<?php echo esc_url($g['website']); ?>">
            <?php echo esc_html($g['funder']); ?>
          </a>
        </h3>
        <p>Type: <?php echo esc_html($g['funder_type']); ?></p>
        <p><strong>Total Giving:</strong> $<?php echo number_format((float)$g['total_giving']); ?></p>
        <p><strong>Average Grant:</strong> $<?php echo number_format((float)$g['avg_grant_amount']); ?></p>
        <p><strong>Assets:</strong> $<?php echo number_format((float)$g['total_assets']); ?></p>
        <p><strong>Status:</strong>
          <button
            type="button"
            class="esgt-status esgt-status-pill"
            data-id="<?php echo esc_attr($g['id']); ?>"
            data-status="<?php echo esc_attr($display_status); ?>"
            aria-label="Change status"
          ><?php echo esc_html($display_status); ?></button>
        </p>
        <a href="#" class="esgt-btn esgt-preview" data-id="<?php echo esc_attr($g['id']); ?>">Preview</a>
        <?php if (is_user_logged_in()): ?>
          <a href="#" class="esgt-btn esgt-write-proposal" data-id="<?php echo esc_attr($g['id']); ?>" data-funder="<?php echo esc_attr($g['funder']); ?>">Write Proposal</a>
        <?php endif; ?>
        <?php if (!empty($g['website'])): ?>
          <a href="<?php echo esc_url($g['website']); ?>" target="_blank" class="esgt-btn">Visit Website</a>
        <?php endif; ?>
      </div>
    <?php endforeach; ?>
  </div>

  <?php if ($totalPages > 1): ?>
    <div class="esgt-pagination">
      <?php if ($page > 1): ?>
        <a href="<?php echo esc_url(add_query_arg(array_merge($_GET, array('pg' => $page - 1)))); ?>" class="esgt-btn">Previous</a>
      <?php endif; ?>
      <span>Page <?php echo $page; ?> of <?php echo $totalPages; ?></span>
      <?php if ($page < $totalPages): ?>
        <a href="<?php echo esc_url(add_query_arg(array_merge($_GET, array('pg' => $page + 1)))); ?>" class="esgt-btn">Next</a>
      <?php endif; ?>
    </div>
  <?php endif; ?>

  
<script type="text/template" id="esgt-suggest-template">
  <div class="esgt-suggest">
    <div class="esgt-suggest-header">
      <h2 class="esgt-suggest-title">Suggest a Grant Opportunity</h2>
      <p class="esgt-suggest-subtitle">Submit a funder you want added to the workspace. Admins review suggestions before import.</p>
    </div>

    <form id="esgt-suggest-form" class="esgt-form">
      <div class="esgt-form-grid">
        <div class="esgt-field">
          <label class="esgt-label" for="esgt_org_name">Organization Name <span class="esgt-required">*</span></label>
          <input id="esgt_org_name" class="esgt-input" type="text" name="organization_name" required placeholder="Foundation or organization name" autocomplete="organization" />
        </div>

        <div class="esgt-field">
          <label class="esgt-label" for="esgt_website_url">Website URL <span class="esgt-required">*</span></label>
          <input id="esgt_website_url" class="esgt-input" type="url" name="website_url" required placeholder="https://example.org" inputmode="url" autocomplete="url" />
        </div>

        <div class="esgt-field">
          <label class="esgt-label" for="esgt_ein">EIN</label>
          <input id="esgt_ein" class="esgt-input" type="text" name="ein" inputmode="numeric" pattern="[0-9]{9}" maxlength="9" placeholder="123456789" />
          <div class="esgt-help">Digits only (9). Optional.</div>
        </div>

        <div class="esgt-field">
          <label class="esgt-label" for="esgt_state">State</label>
          <input id="esgt_state" class="esgt-input" type="text" name="state" maxlength="50" placeholder="CA" autocomplete="address-level1" />
        </div>

        <div class="esgt-field">
          <label class="esgt-label" for="esgt_contact_name">Contact Name</label>
          <input id="esgt_contact_name" class="esgt-input" type="text" name="contact_name" maxlength="255" placeholder="Optional" autocomplete="name" />
        </div>

        <div class="esgt-field">
          <label class="esgt-label" for="esgt_contact_email">Contact Email</label>
          <input id="esgt_contact_email" class="esgt-input" type="email" name="contact_email" maxlength="255" placeholder="Optional" autocomplete="email" />
        </div>
      </div>

      <div class="esgt-field esgt-field-full">
        <label class="esgt-label" for="esgt_rationale">Tell us about the funder <span class="esgt-required">*</span></label>
        <textarea id="esgt_rationale" class="esgt-textarea" name="rationale" required rows="6" placeholder="Tell us about the funder"></textarea>
      </div>

      <div class="esgt-actions">
        <button type="button" class="esgt-btn esgt-btn-secondary" data-close>Cancel</button>
        <button type="submit" class="esgt-btn esgt-btn-primary">Submit Suggestion</button>
      </div>
    </form>
  </div>
</script>

<div id="esgt-modal" class="esgt-modal" aria-hidden="true">
    <div class="esgt-modal-backdrop" data-close></div>
    <div class="esgt-modal-dialog" tabindex="-1">
      <button class="esgt-modal-close" data-close aria-label="Close">&times;</button>
      <div class="esgt-modal-content"></div>
    </div>
  </div>

  <?php
  return ob_get_clean();
});

/* ===============================================
   AJAX: Update Grant (Save Proposal Editor)
=============================================== */

/* ===============================================
   AJAX: Submit Suggested Grant
=============================================== */
add_action('wp_ajax_esgt_submit_suggestion', function(){
  check_ajax_referer('esgt_nonce', 'nonce');

  if (!is_user_logged_in()) {
    wp_send_json_error(['message' => 'Login required']);
  }

  $org = isset($_POST['organization_name']) ? sanitize_text_field(wp_unslash($_POST['organization_name'])) : '';
  $url = isset($_POST['website_url']) ? esc_url_raw(wp_unslash($_POST['website_url'])) : '';
  $ein = isset($_POST['ein']) ? preg_replace('/[^0-9]/', '', wp_unslash($_POST['ein'])) : '';
  $state = isset($_POST['state']) ? sanitize_text_field(wp_unslash($_POST['state'])) : '';
  $contact_name = isset($_POST['contact_name']) ? sanitize_text_field(wp_unslash($_POST['contact_name'])) : '';
  $contact_email = isset($_POST['contact_email']) ? sanitize_email(wp_unslash($_POST['contact_email'])) : '';
  $rationale = isset($_POST['rationale']) ? sanitize_textarea_field(wp_unslash($_POST['rationale'])) : '';

  if ($org === '' || $url === '' || $rationale === '') {
    wp_send_json_error(['message' => 'Missing required fields']);
  }
  if ($ein !== '' && strlen($ein) !== 9) {
    wp_send_json_error(['message' => 'EIN must be 9 digits']);
  }

  $ok = esgt_insert_suggestion([
    'organization_name' => $org,
    'website_url' => $url,
    'ein' => ($ein === '') ? null : $ein,
    'state' => ($state === '') ? null : $state,
    'contact_name' => ($contact_name === '') ? null : $contact_name,
    'contact_email' => ($contact_email === '') ? null : $contact_email,
    'rationale' => $rationale
  ]);

  if ($ok) {
    wp_send_json_success(['message' => 'Suggestion submitted']);
  }
  wp_send_json_error(['message' => 'Unable to save suggestion']);
});

add_action('wp_ajax_esgt_update_grant', function(){
  check_ajax_referer('esgt_nonce', 'nonce');
  $db = new ESGT_DB();

  $id = intval($_POST['id'] ?? 0);
  $data = [
    'status' => sanitize_text_field($_POST['status'] ?? ''),
    'next_task' => sanitize_text_field($_POST['next_task'] ?? ''),
    'next_due' => sanitize_text_field($_POST['next_due'] ?? ''),
    'notes' => sanitize_textarea_field($_POST['notes'] ?? ''),
    'proposal' => wp_kses_post($_POST['proposal'] ?? '')
  ];

  $ok = $db->update_grant($id, $data);
  if ($ok) wp_send_json_success(['message' => 'Grant updated']);
  else wp_send_json_error(['message' => 'Database update failed']);
});

/* ===============================================
   AJAX: Update Grant Status (Status Pill)
=============================================== */
add_action('wp_ajax_esgt_update_grant_status', function(){
  check_ajax_referer('esgt_nonce', 'nonce');

  $id = intval($_POST['id'] ?? 0);
  if (!$id) wp_send_json_error(['message' => 'Missing grant ID']);

  $status = sanitize_text_field($_POST['status'] ?? '');
  $allowed = ['Researching','Planned','In Progress','Submitted','Awarded','Declined'];
  if (!in_array($status, $allowed, true)) {
    wp_send_json_error(['message' => 'Invalid status']);
  }

  try {
    $db = new ESGT_DB();
    $ok = $db->update_grant_status($id, $status);
    if ($ok) wp_send_json_success(['message' => 'Status updated']);
    wp_send_json_error(['message' => 'Database update failed']);
  } catch (Exception $e) {
    wp_send_json_error(['message' => $e->getMessage()]);
  }
});

/* =======================================================
   Modal Preview (includes/modal-funder-preview.php)
======================================================= */
add_action('wp_ajax_esgt_preview_grant', function(){
  check_ajax_referer('esgt_nonce', 'nonce');
  require_once ESGT_PRO_PATH . 'includes/modal-funder-preview.php';
  exit;
});
add_action('wp_ajax_nopriv_esgt_preview_grant', function(){
  require_once ESGT_PRO_PATH . 'includes/modal-funder-preview.php';
  exit;
});

/* =======================================================
   IRS 990 Proxy – Server-Side Fetch (CORS Safe)
======================================================= */
add_action('wp_ajax_esgt_get_irs990', 'esgt_get_irs990');
add_action('wp_ajax_nopriv_esgt_get_irs990', 'esgt_get_irs990');

function esgt_get_irs990() {
  check_ajax_referer('esgt_nonce', 'nonce');
  $ein = sanitize_text_field($_GET['ein'] ?? '');
  if (empty($ein)) wp_send_json_error(['message' => 'Missing EIN.']);

  $url = "https://projects.propublica.org/nonprofits/api/v2/organizations/{$ein}.json";
  $response = wp_remote_get($url, ['timeout' => 10]);
  if (is_wp_error($response)) wp_send_json_error(['message' => 'Failed to fetch IRS data.']);
  $body = wp_remote_retrieve_body($response);
  if (!$body) wp_send_json_error(['message' => 'Empty IRS response.']);

  $data = json_decode($body, true);
  wp_send_json_success($data);
}

/* Proposal editor removed in v1.5: TinyMCE modal and related scripts have been deleted */

/* Proposal draft AJAX endpoints removed in v1.5 */
/* =======================================================
   REST API Endpoint: /wp-json/esgt/v1/grants
   Returns normalized grant data from external DB
======================================================= */
add_action('rest_api_init', function() {
  register_rest_route('esgt/v1', '/grants', [
    'methods'  => 'GET',
    'callback' => 'esgt_rest_list_grants',
    'permission_callback' => 'esgt_rest_can_view'
  ]);
});


function esgt_rest_can_view($request) {
  if (!is_user_logged_in()) return false;
  if (current_user_can('manage_options')) return true;
  $user = wp_get_current_user();
  return in_array('intern', (array) $user->roles, true);
}

function esgt_rest_list_grants($request) {
  $opts = get_option('esgt_db', []);
  try {
    $pdo = new PDO(
      sprintf('mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4',
        $opts['host'], $opts['port'], $opts['name']
      ),
      $opts['user'], $opts['pass']
    );
  } catch (Exception $e) {
    return new WP_Error('db_connect_error', 'Database connection failed: ' . $e->getMessage(), ['status' => 500]);
  }

  /* ----------------------------
     Parameters
  ---------------------------- */
  $limit  = intval($request->get_param('limit') ?: 50);
  $page   = intval($request->get_param('page') ?: 1);
  $offset = ($page - 1) * $limit;

  $state  = sanitize_text_field($request->get_param('state') ?: '');
  $funder = sanitize_text_field($request->get_param('funder') ?: '');
  $status = sanitize_text_field($request->get_param('status') ?: '');
  $search = sanitize_text_field($request->get_param('search') ?: '');
  $format = sanitize_text_field($request->get_param('format') ?: 'json');

  /* ----------------------------
     Query Builder
  ---------------------------- */
  $sql = "SELECT id, title, funder, funder_type, deadline, amount, status, website 
          FROM grants WHERE 1=1";
  $params = [];

  if ($state) {
    $sql .= " AND state = :state";
    $params[':state'] = $state;
  }
  if ($funder) {
    $sql .= " AND funder LIKE :funder";
    $params[':funder'] = '%' . $funder . '%';
  }
  if ($status) {
    $sql .= " AND status = :status";
    $params[':status'] = $status;
  }
  if ($search) {
    $sql .= " AND (title LIKE :search OR funder LIKE :search)";
    $params[':search'] = '%' . $search . '%';
  }

  // Deterministic ordering prevents duplicates across pages when using LIMIT/OFFSET.
  $sql .= " ORDER BY (deadline IS NULL) ASC, deadline ASC, id ASC LIMIT :limit OFFSET :offset";

  $stmt = $pdo->prepare($sql);
  foreach ($params as $key => $val) {
    $stmt->bindValue($key, $val);
  }
  $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
  $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
  $stmt->execute();
  $data = $stmt->fetchAll(PDO::FETCH_ASSOC);

  /* ----------------------------
     Total Count
  ---------------------------- */
  // Count should match the same filters as the paginated query.
  $countSql = "SELECT COUNT(*) FROM grants WHERE 1=1";
  if ($state)  $countSql .= " AND state = :state";
  if ($funder) $countSql .= " AND funder LIKE :funder";
  if ($status) $countSql .= " AND status = :status";
  if ($search) $countSql .= " AND (title LIKE :search OR funder LIKE :search)";

  $countStmt = $pdo->prepare($countSql);
  foreach ($params as $key => $val) {
    $countStmt->bindValue($key, $val);
  }
  $countStmt->execute();
  $total = $countStmt->fetchColumn();

  /* ----------------------------
     CSV Export (format=csv)
  ---------------------------- */
  if ($format === 'csv') {
    header('Content-Type: text/csv');
    header('Content-Disposition: attachment; filename="grants.csv"');

    $output = fopen('php://output', 'w');
    if (!empty($data)) {
      fputcsv($output, array_keys($data[0]));
      foreach ($data as $row) {
        fputcsv($output, $row);
      }
    }
    fclose($output);
    exit;
  }

  /* ----------------------------
     JSON Response
  ---------------------------- */
  return rest_ensure_response([
    'page'  => $page,
    'limit' => $limit,
    'total' => intval($total),
    'count' => count($data),
    'data'  => $data
  ]);
}
