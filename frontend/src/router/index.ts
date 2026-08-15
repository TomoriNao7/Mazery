import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
  {
    path: '/library',
    component: () => import('../views/LibraryView.vue'),
    children: [
      { path: '', redirect: '/library/local' },
      { path: 'local', name: 'local-library', component: () => import('../views/LocalLibraryView.vue') },
      { path: 'history', name: 'history-library', component: () => import('../views/HistoryLibraryView.vue') },
      { path: 'create', name: 'create', component: () => import('../views/ScriptCreateView.vue') },
    ],
  },
  { path: '/create', redirect: '/library/create' },
  { path: '/script/:id/select', name: 'role-select', component: () => import('../views/RoleSelectView.vue') },
  { path: '/game/:id', name: 'game', component: () => import('../views/GameView.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
