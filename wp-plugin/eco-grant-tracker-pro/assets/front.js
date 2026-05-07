(function($){

  /* ========================================================
     (LEGACY CLEANUP) – make sure any leftover inline rows are gone
  ======================================================== */
  $(function(){ $('.esgt-edit-row').remove(); });

  /* ========================================================
     MODAL PREVIEW
  ======================================================== */
  function openModal(html){
    const $m = $('#esgt-modal');
    $m.removeClass('is-open').attr('aria-hidden','true');
    $m.find('.esgt-modal-content').html(html);
    void $m[0].offsetWidth;
    $m.attr('aria-hidden','false').addClass('is-open');
    $('body').addClass('esgt-modal-open');
  }
  function closeModal(){
    const $m = $('#esgt-modal');
    $m.removeClass('is-open').attr('aria-hidden','true');
    $m.find('.esgt-modal-content').empty();
    $('body').removeClass('esgt-modal-open');
  }

  $(document).on('click','.esgt-preview',function(e){
    e.preventDefault();
    const id = $(this).data('id');
    $.post(ESGT.ajax_url,{action:'esgt_preview_grant',id:id,nonce:ESGT.nonce},function(resp){
      if(resp && resp.success && resp.data?.html) openModal(resp.data.html);
      else alert('Preview not available.');
    });
  });
  $(document).on('click','#esgt-modal [data-close],#esgt-modal .esgt-modal-backdrop',closeModal);
  $(document).on('keydown',e=>{ if(e.key==='Escape') closeModal(); });

  
/* ========================================================
   SUGGEST GRANT MODAL
======================================================== */
function openSuggestModal(){
  const tpl = $('#esgt-suggest-template').html();
  if(!tpl){ alert('Suggest form not available.'); return; }
  openModal(tpl);
}

$(document).on('click','#esgt-open-suggest',function(e){
  e.preventDefault();
  openSuggestModal();
});

$(document).on('submit','#esgt-suggest-form',function(e){
  e.preventDefault();
  const $form = $(this);
  const data = {
    action: 'esgt_submit_suggestion',
    nonce: ESGT.nonce,
    organization_name: $form.find('[name="organization_name"]').val() || '',
    website_url: $form.find('[name="website_url"]').val() || '',
    ein: ($form.find('[name="ein"]').val() || '').replace(/[^0-9]/g,''),
    state: $form.find('[name="state"]').val() || '',
    contact_name: $form.find('[name="contact_name"]').val() || '',
    contact_email: $form.find('[name="contact_email"]').val() || '',
    rationale: $form.find('[name="rationale"]').val() || ''
  };

  const $btn = $form.find('button[type="submit"]');
  $btn.prop('disabled', true).text('Submitting...');

  $.post(ESGT.ajax_url, data, function(resp){
    if(resp && resp.success){
      closeModal();
      alert('Submitted. Admins will review your suggestion.');
    } else {
      const msg = resp?.data?.message || 'Unable to submit suggestion.';
      alert(msg);
    }
  }).fail(function(){
    alert('Network error. Please try again.');
  }).always(function(){
    $btn.prop('disabled', false).text('Submit Suggestion');
  });
});

/* ========================================================
   SEARCH + FILTER (server-side)
======================================================== */
function setHidden(el, hidden){
  if(hidden){ el.attr('hidden', true); }
  else { el.removeAttr('hidden'); }
}

$(document).on('click', '.esgt-advanced-toggle', function(e){
  e.preventDefault();
  const $btn = $(this);
  const $panel = $('.esgt-advanced-panel');
  const isHidden = $panel.is('[hidden]');
  setHidden($panel, !isHidden);
  $btn.attr('aria-expanded', isHidden ? 'true' : 'false');
});

// Auto-submit when status changes
$(document).on('change', '.esgt-status-filter', function(){
  const $form = $(this).closest('form');
  $form.find('input[name="pg"]').val('1');
  $form.trigger('submit');
});

// Enter in search applies filters
$(document).on('keydown', '.esgt-search', function(e){
  if(e.key === 'Enter'){
    const $form = $(this).closest('form');
    $form.find('input[name="pg"]').val('1');
  }
});

/* ========================================================
     PROPUBLICA EIN TOOLS (Profile)
  ======================================================== */
  function normalizeEin(raw){
    return String(raw || '').replace(/[^0-9]/g,'').trim();
  }

  function openProPublicaProfile(ein){
    const clean = normalizeEin(ein);
    if(!clean) return alert('Please enter an EIN.');
    window.open(`https://projects.propublica.org/nonprofits/organizations/${clean}`, '_blank', 'noopener');
  }

  // Toolbar EIN button
  $(document).on('click', '.esgt-ein-propublica', function(e){
    e.preventDefault();
    const ein = $('.esgt-ein').val();
    openProPublicaProfile(ein);
  });

  /* ========================================================
     ADVANCED FILTER UI UPGRADES
     - Segmented Any/All toggles (sync with <select>)
     - Active filter chips with "clear one"
     - Auto-open Advanced when active
  ======================================================== */
  function getParams(){
    return new URLSearchParams(window.location.search || '');
  }

  function hasAnyAdvancedParam(params){
    const keys = ['mk','pak','gk','ftk','exk','global_in','global_ex'];
    return keys.some(k => (params.get(k) || '').trim() !== '');
  }

  function humanMode(val){
    return (String(val || '').toLowerCase() === 'all') ? 'All' : 'Any';
  }

  function buildChip($wrap, label, value, removeKeys){
    const $chip = $('<span class="esgt-chip" />');
    const $txt = $('<span class="esgt-chip-text" />').text(label + ': ' + value);
    const $btn = $('<button type="button" class="esgt-chip-x" aria-label="Remove filter">×</button>');
    $btn.on('click', function(){
      const params = getParams();
      (removeKeys || []).forEach(k => params.delete(k));
      // Always reset page when filters change
      params.delete('pg');
      const qs = params.toString();
      const next = window.location.pathname + (qs ? ('?' + qs) : '');
      window.location.assign(next);
    });
    $chip.append($txt).append($btn);
    $wrap.append($chip);
  }

  function renderActiveChips(){
    const $wrap = $('.esgt-active-filters');
    if(!$wrap.length) return;

    const params = getParams();
    $wrap.empty();

    const add = (label, key, modeKey) => {
      const v = (params.get(key) || '').trim();
      if(!v) return;
      const mode = modeKey ? humanMode(params.get(modeKey)) : null;
      const display = mode ? (v + ' (' + mode + ')') : v;
      const removeKeys = modeKey ? [key, modeKey] : [key];
      buildChip($wrap, label, display, removeKeys);
    };

    // Basic
    add('Search', 'q');
    add('Status', 'status');
    add('EIN', 'ein');

    // Advanced (within field)
    add('Mission', 'mk', 'mk_mode');
    add('Program area', 'pak', 'pak_mode');
    add('Geographic focus', 'gk', 'gk_mode');
    add('Funding type', 'ftk', 'ftk_mode');
    add('Exclusion', 'exk', 'exk_mode');

    // Global (across fields)
    add('Global include', 'global_in', 'global_in_mode');
    add('Global exclude', 'global_ex');

    if($wrap.children().length){
      $wrap.removeAttr('hidden');
    } else {
      $wrap.attr('hidden', true);
    }
  }

  function upgradeModeSelectsToSegmented(){
    $('.esgt-advanced-panel select[name$="_mode"]').each(function(){
      const $sel = $(this);
      if($sel.data('segmented')) return;
      $sel.data('segmented', true);

      $sel.addClass('esgt-seg-select');

      const current = ($sel.val() || 'any').toLowerCase();
      const $seg = $('<div class="esgt-seg" role="group" aria-label="Within this field match mode"></div>');

      const makeBtn = (val, label) => {
        const $b = $('<button type="button" class="esgt-seg-btn"></button>').text(label);
        $b.attr('data-val', val);
        if(current === val) $b.addClass('is-active');
        $b.on('click', function(){
          $sel.val(val).trigger('change');
          $seg.find('.esgt-seg-btn').removeClass('is-active');
          $b.addClass('is-active');
        });
        return $b;
      };

      $seg.append(makeBtn('any','Any')).append(makeBtn('all','All'));
      $sel.before($seg);
    });
  }

  function autoOpenAdvancedIfActive(){
    const params = getParams();
    if(!hasAnyAdvancedParam(params)) return;

    const $panel = $('.esgt-advanced-panel');
    const $btn = $('.esgt-advanced-toggle');
    if($panel.length){
      setHidden($panel, false);
      if($btn.length) $btn.attr('aria-expanded', 'true');
    }
  }

  $(function(){
    upgradeModeSelectsToSegmented();
    renderActiveChips();
    autoOpenAdvancedIfActive();
  });

  /* ========================================================
     STATUS PILL (inline status changes)
  ======================================================== */
  let $statusMenu = null;

  function closeStatusMenu(){
    if($statusMenu){
      $statusMenu.remove();
      $statusMenu = null;
    }
  }

  function buildStatusMenu($pill){
    closeStatusMenu();

    const id = parseInt($pill.data('id'), 10);
    if(!id) return;

    const current = String($pill.data('status') || $pill.text() || '').trim();
    const statuses = (ESGT && Array.isArray(ESGT.statuses))
      ? ESGT.statuses
      : ['Researching','Planned','In Progress','Submitted','Awarded','Declined'];

    $statusMenu = $('<div class="esgt-status-menu" role="menu" />');

    statuses.forEach(function(s){
      const $b = $('<button type="button" class="esgt-status-menu-item" role="menuitem" />');
      $b.text(s);
      if(String(s) === current) $b.addClass('is-active');
      $b.on('click', function(e){
        e.preventDefault();
        e.stopPropagation();
        if(String(s) === current){
          closeStatusMenu();
          return;
        }
        // Optimistic UI
        $pill.text(s).attr('data-status', s).data('status', s);

        $.post(ESGT.ajax_url, {
          action: 'esgt_update_grant_status',
          id: id,
          status: s,
          nonce: ESGT.nonce
        }, function(resp){
          if(!(resp && resp.success)){
            // revert
            $pill.text(current).attr('data-status', current).data('status', current);
            alert(resp?.data?.message || 'Status update failed.');
          }
          closeStatusMenu();
        }).fail(function(){
          $pill.text(current).attr('data-status', current).data('status', current);
          closeStatusMenu();
          alert('Status update failed.');
        });
      });
      $statusMenu.append($b);
    });

    $('body').append($statusMenu);

    // Position near pill
    const r = $pill[0].getBoundingClientRect();
    const top = r.bottom + window.scrollY + 6;
    const left = r.left + window.scrollX;
    $statusMenu.css({ top: top + 'px', left: left + 'px' });
  }

  $(document).on('click', '.esgt-status-pill', function(e){
    e.preventDefault();
    e.stopPropagation();
    const $pill = $(this);
    if($statusMenu){
      // If clicking same pill, toggle
      closeStatusMenu();
      return;
    }
    buildStatusMenu($pill);
  });

  $(document).on('click', function(){
    closeStatusMenu();
  });

  $(document).on('keydown', function(e){
    if(e.key === 'Escape') closeStatusMenu();
  });


  /* ========================================================
     ADVANCED FILTER UI UPGRADES
     - Segmented Any/All toggles (sync with <select>)
     - Active filter chips with clear-one
     - Auto-open Advanced when active
  ======================================================== */
  function getParams(){
    return new URLSearchParams(window.location.search || '');
  }

  function hasAnyAdvancedParam(params){
    const keys = ['mk','pak','gk','ftk','exk','global_in','global_ex'];
    return keys.some(k => (params.get(k) || '').trim() !== '');
  }

  function humanMode(val){
    return (String(val || '').toLowerCase() === 'all') ? 'All' : 'Any';
  }

  function buildChip($wrap, label, value, removeKeys){
    const $chip = $('<span class="esgt-chip" />');
    const $txt = $('<span class="esgt-chip-text" />').text(label + ': ' + value);
    const $btn = $('<button type="button" class="esgt-chip-x" aria-label="Remove filter">×</button>');
    $btn.on('click', function(){
      const params = getParams();
      (removeKeys || []).forEach(k => params.delete(k));
      params.delete('pg');
      const qs = params.toString();
      const next = window.location.pathname + (qs ? ('?' + qs) : '');
      window.location.assign(next);
    });
    $chip.append($txt).append($btn);
    $wrap.append($chip);
  }

  function renderActiveChips(){
    const $wrap = $('.esgt-active-filters');
    if(!$wrap.length) return;

    const params = getParams();
    $wrap.empty();

    const add = (label, key, modeKey) => {
      const v = (params.get(key) || '').trim();
      if(!v) return;
      const mode = modeKey ? humanMode(params.get(modeKey)) : null;
      const display = mode ? (v + ' (' + mode + ')') : v;
      const removeKeys = modeKey ? [key, modeKey] : [key];
      buildChip($wrap, label, display, removeKeys);
    };

    add('Search', 'q');
    add('Status', 'status');
    add('EIN', 'ein');

    add('Mission', 'mk', 'mk_mode');
    add('Program area', 'pak', 'pak_mode');
    add('Geographic focus', 'gk', 'gk_mode');
    add('Funding type', 'ftk', 'ftk_mode');
    add('Exclusion', 'exk', 'exk_mode');

    add('Global include', 'global_in', 'global_in_mode');
    add('Global exclude', 'global_ex');

    if($wrap.children().length){
      $wrap.removeAttr('hidden');
    } else {
      $wrap.attr('hidden', true);
    }
  }

  function upgradeModeSelectsToSegmented(){
    $('.esgt-advanced-panel select[name$="_mode"]').each(function(){
      const $sel = $(this);
      if($sel.data('segmented')) return;
      $sel.data('segmented', true);

      $sel.addClass('esgt-seg-select');

      const current = ($sel.val() || 'any').toLowerCase();
      const $seg = $('<div class="esgt-seg" role="group" aria-label="Within this field match mode"></div>');

      const makeBtn = (val, label) => {
        const $b = $('<button type="button" class="esgt-seg-btn"></button>').text(label);
        $b.attr('data-val', val);
        if(current === val) $b.addClass('is-active');
        $b.on('click', function(){
          $sel.val(val).trigger('change');
          $seg.find('.esgt-seg-btn').removeClass('is-active');
          $b.addClass('is-active');
        });
        return $b;
      };

      $seg.append(makeBtn('any','Any')).append(makeBtn('all','All'));
      $sel.before($seg);
    });
  }

  function autoOpenAdvancedIfActive(){
    const params = getParams();
    if(!hasAnyAdvancedParam(params)) return;

    const $panel = $('.esgt-advanced-panel');
    const $btn = $('.esgt-advanced-toggle');
    if($panel.length){
      setHidden($panel, false);
      if($btn.length) $btn.attr('aria-expanded', 'true');
    }
  }

  $(function(){
    upgradeModeSelectsToSegmented();
    renderActiveChips();
    autoOpenAdvancedIfActive();
  });


})(jQuery);
