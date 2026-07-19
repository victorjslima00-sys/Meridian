import axios from 'axios';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
});

// Browser code cannot safely contain a shared backend secret. If a development
// key is explicitly supplied, use it only for local/private environments.
const developmentKey = import.meta.env.VITE_API_KEY;
if (developmentKey) {
  api.defaults.headers.common['X-API-Key'] = developmentKey;
}

export default api;
