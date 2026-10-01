// AI-ASSISTED: the client routes: join at `/`, the quiz at `/quiz/:quizId` (only for the joined quiz), the share link and a 404 page.
import { createRouter, createWebHistory, type RouteRecordRaw, type RouterHistory } from 'vue-router'
import { useQuizStore } from '@/stores/quiz'

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'join', component: () => import('@/views/JoinView.vue') },
  {
    path: '/quiz/:quizId',
    name: 'quiz',
    component: () => import('@/views/PlayView.vue'),
    props: true,
  },
  // Short share link: the join screen with the quiz ID filled in.
  { path: '/q/:quizId', redirect: (to) => ({ name: 'join', query: { quiz: to.params.quizId } }) },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
  },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({ history, routes })
  // The quiz screen needs a store joined to that quiz, or the results of an ended one (a join after the end binds no
  // quiz). A direct load, a refresh or another ID goes to the join screen with the ID filled in, like `/q/:quizId`.
  router.beforeEach((to) => {
    if (to.name !== 'quiz') return
    const store = useQuizStore()
    const joined = store.quiz === null ? store.ended : store.quiz.quizId === to.params.quizId
    if (!joined) return { name: 'join', query: { quiz: to.params.quizId } }
  })
  return router
}
