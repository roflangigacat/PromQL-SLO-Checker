const { createApp, reactive, ref, onMounted, onUnmounted, nextTick } = Vue;

const app = createApp({
  delimiters: ['[[', ']]'],
  setup() {
    const urlParams = new URLSearchParams(window.location.search);
    const urlToken = urlParams.get('token');
    const urlUser = urlParams.get('user');
    if (urlToken) {
      localStorage.setItem('token', urlToken);
      localStorage.setItem('username', urlUser);
      document.cookie = `token=${urlToken}; path=/; max-age=86400`;
      document.cookie = `username=${urlUser}; path=/; max-age=86400`;
      window.history.replaceState({}, document.title, "/");
    }

    function getCookie(name) {
      const value = `; ${document.cookie}`;
      const parts = value.split(`; ${name}=`);
      if (parts.length === 2) return parts.pop().split(';').shift();
      return '';
    }

    const tab = ref('query');
    const username = ref(localStorage.getItem('username') || getCookie('username') || '');
    const token = ref(localStorage.getItem('token') || getCookie('token') || '');
    const currentUser = ref(null);
    const loading = ref(false);

    const datasources = ref([]);
    const queries = ref([]);
    const profiles = ref([]);
    const history = ref([]);

    const q = reactive({
      name: '',
      datasource_id: null,
      promql: 'avg_over_time(node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate{namespace="da-nt03-om-lt-view-01",pod="graf-grafana-devops-7ee841-6f6b6f7c4f-9vlc8",container="graf-grafana"}[1h])',
      description: '',
      start_time: '',
      end_time: '',
      step: '60s',
      condition_min: 0.6,
      condition_max: 0.8,
    });

    const result = ref(null);
    const newDs = reactive({ name: '', url: 'http://10.21.12.3:9090', ds_type: 'prometheus' });
    const newProfile = reactive({ name: '', query_ids: [], is_public: false });
    const profileRun = reactive({ start: '', end: '' });
    const profileResult = ref(null);

    function apiHeaders() {
      return {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token.value}`,
      };
    }
    async function api(path, opts = {}) {
      const r = await fetch(path, { ...opts, headers: { ...apiHeaders(), ...(opts.headers || {}) } });
      if (r.status === 401 || r.status === 403) {
        logout();
        throw new Error('Сессия истекла');
      }
      return r;
    }

    function logout() {
      localStorage.removeItem('token');
      localStorage.removeItem('username');
      document.cookie = 'token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
      document.cookie = 'username=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
      window.location.href = '/login';
    }

    async function loadCurrentUser() {
      try {
        const r = await api('/api/auth/me');
        const data = await r.json();
        currentUser.value = data.id;
      } catch (e) {
        console.error('Failed to load current user:', e);
      }
    }

    async function loadHistory() {
      try {
        const r = await api('/api/history');
        history.value = await r.json();
      } catch (e) {
        console.error('Failed to load history:', e);
      }
    }

    async function loadDatasources() {
      const r = await api('/api/datasources');
      datasources.value = await r.json();
      if (datasources.value.length && !q.datasource_id) q.datasource_id = datasources.value[0].id;
    }
    async function addDatasource() {
      if (!newDs.name || !newDs.url) return alert('Заполните поля');
      await api('/api/datasources', { method: 'POST', body: JSON.stringify(newDs) });
      newDs.name = ''; newDs.url = 'http://10.21.12.3:9090';
      await loadDatasources();
    }
    async function deleteDs(id) {
      if (!confirm('Удалить источник?')) return;
      await api(`/api/datasources/${id}`, { method: 'DELETE' });
      await loadDatasources();
    }
    async function checkDs(id) {
      const r = await api(`/api/datasources/${id}/check`, { method: 'POST' });
      const data = await r.json();
      const ds = datasources.value.find(d => d.id === id);
      if (ds) ds._check = data;
    }

    async function getLabels(dsId) {
      try {
        const r = await api(`/api/datasources/${dsId}/labels`);
        return await r.json();
      } catch (e) {
        console.error('Failed to get labels:', e);
        return [];
      }
    }
    
    async function getLabelValues(dsId, labelName) {
      try {
        const r = await api(`/api/datasources/${dsId}/label-values/${labelName}`);
        return await r.json();
      } catch (e) {
        console.error('Failed to get label values:', e);
        return [];
      }
    }
    
    const suggestions = ref([]);
    let suggestionsTimeout = null;
    
    async function onPromqlInput() {
      clearTimeout(suggestionsTimeout);
      
      suggestionsTimeout = setTimeout(async () => {
        if (!q.datasource_id || !q.promql) {
          suggestions.value = [];
          return;
        }
        
        const activeLabel = parsePromqlForActiveLabel(q.promql);
        if (!activeLabel) {
          suggestions.value = [];
          return;
        }
        
        const allValues = await getLabelValues(q.datasource_id, activeLabel.labelName);
        
        const prefix = activeLabel.currentValue.toLowerCase();
        const filtered = allValues.filter(v => 
          v.toLowerCase().startsWith(prefix)
        );
        
        suggestions.value = filtered.slice(0, 30);
      }, 200);
    }
    
    function selectSuggestion(value) {
      const activeLabel = parsePromqlForActiveLabel(q.promql);
      if (!activeLabel) return;
      
      const before = q.promql.substring(0, activeLabel.startIndex);
      const after = q.promql.substring(activeLabel.endIndex);
      q.promql = before + value + after;
      
      suggestions.value = [];
    }

    function parsePromqlForActiveLabel(promql) {
      const labelRegex = /(\w+)="([^"]*)"/g;
      let match;
      let lastMatch = null;
      
      while ((match = labelRegex.exec(promql)) !== null) {
        lastMatch = {
          labelName: match[1],
          currentValue: match[2],
          startIndex: match.index + match[1].length + 2,
          endIndex: match.index + match[0].length - 1,
          fullMatch: match[0]
        };
      }
      
      return lastMatch;
    }

    function dsName(id) {
      const ds = datasources.value.find(d => d.id === id);
      return ds ? ds.name : `#${id}`;
    }

    async function loadQueries() {
      const r = await api('/api/queries');
      queries.value = await r.json();
    }
    async function saveQuery() {
      if (!q.name) return alert('Укажите имя запроса');
      if (!q.datasource_id) return alert('Выберите источник');
      await api('/api/queries', {
        method: 'POST',
        body: JSON.stringify({
          name: q.name,
          promql: q.promql,
          datasource_id: q.datasource_id,
          step: q.step,
          condition_min: q.condition_min === "" ? null : parseFloat(q.condition_min),
          condition_max: q.condition_max === "" ? null : parseFloat(q.condition_max),
          description: q.description,
        }),
      });
      alert('Сохранено');
    }
    async function deleteQuery(id) {
      if (!confirm('Удалить запрос?')) return;
      await api(`/api/queries/${id}`, { method: 'DELETE' });
      await loadQueries();
    }
    function loadQueryToEditor(saved) {
      q.name = saved.name;
      q.promql = saved.promql;
      q.datasource_id = saved.datasource_id;
      q.step = saved.step;
      q.condition_min = saved.condition_min;
      q.condition_max = saved.condition_max;
      q.description = saved.description || '';
      tab.value = 'query';
    }
    function loadQueryToEditorFromResult(f) {
      q.name = f.query_name;
      q.promql = f.promql;
      q.datasource_id = f.datasource_id || null;
      q.step = '60s';
      q.condition_min = f.condition_min;
      q.condition_max = f.condition_max;
      q.description = f.description || '';
      tab.value = 'query';
    }

    function replayQuery(queryData) {
      console.log('🔄 Replay query:', queryData.query_name);
      
      q.name = queryData.query_name;
      q.promql = queryData.promql;
      q.datasource_id = queryData.datasource_id;
      q.step = queryData.step || '60s';
      q.condition_min = queryData.condition_min;
      q.condition_max = queryData.condition_max;
      q.description = queryData.description || '';
      
      tab.value = 'query';
      
      setTimeout(() => {
        runQuery();
      }, 100);
    }

    async function loadProfiles() {
      const r = await api('/api/profiles');
      profiles.value = await r.json();
    }
    async function createProfile() {
      if (!newProfile.name) return alert('Имя профиля');
      await api('/api/profiles', {
        method: 'POST',
        body: JSON.stringify({ 
          name: newProfile.name, 
          query_ids: newProfile.query_ids,
          is_public: newProfile.is_public
        }),
      });
      newProfile.name = ''; 
      newProfile.query_ids = []; 
      newProfile.is_public = false;
      await loadProfiles();
    }
    async function deleteProfile(id) {
      if (!confirm('Удалить профиль?')) return;
      await api(`/api/profiles/${id}`, { method: 'DELETE' });
      await loadProfiles();
    }
    async function copyProfile(profileId) {
      if (!confirm('Добавить этот публичный профиль себе?')) return;
      try {
        await api(`/api/profiles/${profileId}/copy`, { method: 'POST' });
        alert('Профиль скопирован!');
        await loadProfiles();
      } catch (e) {
        alert('Ошибка: ' + e.message);
      }
    }
    async function runProfile(id) {
      if (!profileRun.start || !profileRun.end) return alert('Укажите время');
      loading.value = true;
      try {
        const r = await api('/api/profiles/execute', {
          method: 'POST',
          body: JSON.stringify({
            profile_id: id,
            start_time: new Date(profileRun.start).toISOString(),
            end_time: new Date(profileRun.end).toISOString(),
            step: '60s',
          }),
        });
        profileResult.value = await r.json();
      } finally { loading.value = false; }
    }

    async function runQuery() {
      if (!q.datasource_id) return alert('Выберите источник');
      if (!q.start_time || !q.end_time) return alert('Укажите время');
      loading.value = true;
      result.value = null;
      try {
        const r = await api('/api/execute', {
          method: 'POST',
          body: JSON.stringify({
            datasource_id: q.datasource_id,
            promql: q.promql,
            start_time: new Date(q.start_time).toISOString(),
            end_time: new Date(q.end_time).toISOString(),
            step: q.step,
            condition_min: q.condition_min === "" ? null : parseFloat(q.condition_min),
            condition_max: q.condition_max === "" ? null : parseFloat(q.condition_max),
          }),
        });
        result.value = await r.json();
        await nextTick();
        drawChart();
      } finally { loading.value = false; }
    }

    function drawChart() {
      const el = document.getElementById('chart');
      if (!el || !result.value || !result.value.raw_data) return;
      const chart = echarts.init(el);
      const series = [];
      result.value.raw_data.forEach((s, idx) => {
        const label = Object.entries(s.metric).map(([k, v]) => `${k}="${v}"`).join(', ');
        const data = s.values.map(([t, v]) => [t * 1000, parseFloat(v)]);
        series.push({ name: label || `series-${idx}`, type: 'line', showSymbol: false, data, lineStyle: { width: 2 } });
      });
      const markArea = [];
      if (q.condition_min != null && q.condition_max != null) {
        markArea.push([
          { yAxis: q.condition_min, itemStyle: { color: 'rgba(103,194,58,0.08)' } },
          { yAxis: q.condition_max },
        ]);
      }
      if (result.value.violations && result.value.violations.length) {
        const vData = result.value.violations.map(v => [v.timestamp * 1000, v.value]);
        series.push({ name: 'Нарушения', type: 'scatter', symbolSize: 8, itemStyle: { color: '#f56c6c' }, data: vData, z: 10 });
      }
      chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { top: 0, type: 'scroll' },
        grid: { left: 60, right: 30, top: 40, bottom: 40 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value', scale: true },
        dataZoom: [{ type: 'inside' }, { type: 'slider' }],
        series: series.map((s) => {
          if (s.type === 'line' && markArea.length) {
            s.markArea = { silent: true, data: markArea };
            s.markLine = {
              silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: '#67c23a' },
              data: [
                { yAxis: q.condition_min, label: { formatter: `min ${q.condition_min}` } },
                { yAxis: q.condition_max, label: { formatter: `max ${q.condition_max}` } },
              ],
            };
          }
          return s;
        }),
      });
      window.addEventListener('resize', () => chart.resize());
    }

    function formatDate(ts) { return new Date(ts * 1000).toLocaleString('ru-RU'); }
    function formatLabels(labels) { return Object.entries(labels).map(([k, v]) => `${k}=${v}`).join(', '); }
    function setDefaultTime() {
      const now = new Date();
      const start = new Date(now); start.setHours(12, 0, 0, 0);
      const end = new Date(now); end.setHours(13, 0, 0, 0);
      const pad = n => String(n).padStart(2, '0');
      const fmt = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
      q.start_time = fmt(start); q.end_time = fmt(end);
      profileRun.start = fmt(start); profileRun.end = fmt(end);
    }

    const handleClickOutside = (e) => {
      if (!e.target.closest('.autocomplete-dropdown') && !e.target.closest('textarea')) {
        suggestions.value = [];
      }
    };

    onMounted(async () => {
      if (!token.value) { 
        window.location.href = '/login'; 
        return; 
      }
      
      await loadCurrentUser();
      setDefaultTime();
      await loadDatasources();
      await loadQueries();
      await loadProfiles();
      document.addEventListener('click', handleClickOutside);
    });
    onUnmounted(() => {
      document.removeEventListener('click', handleClickOutside);
    });

    return {
      tab, username, loading, currentUser,
      datasources, queries, profiles, history, suggestions,
      q, result, newDs, newProfile, profileRun, profileResult,
      addDatasource, deleteDs, checkDs, dsName,
      saveQuery, deleteQuery, loadQueryToEditor, loadQueryToEditorFromResult, 
      onPromqlInput, selectSuggestion,
      loadProfiles, replayQuery, loadHistory, getLabels, getLabelValues, parsePromqlForActiveLabel,
      createProfile, deleteProfile, copyProfile, runProfile,
      runQuery, formatDate, formatLabels, logout,
    };
  },
});

app.use(ElementPlus);
app.mount('#app');