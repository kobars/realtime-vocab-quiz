// AI-ASSISTED: the client routes: join at `/`, the quiz at `/quiz/:quizId`, and a 404 page.
import { createRouter, createWebHistory, type RouteRecordRaw, type RouterHistory } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'join', component: () => import('@/views/JoinView.vue') },
  {
    path: '/quiz/:quizId',
    name: 'quiz',
    component: () => import('@/views/QuizView.vue'),
    props: true,
  },
  // Short share link.
  { path: '/q/:quizId', redirect: (to) => ({ name: 'quiz', params: to.params }) },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
  },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
