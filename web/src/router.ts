// AI-ASSISTED: the client routes: join at `/`, the quiz at `/quiz/:quizId` (only for the joined quiz, which a reload joins again), the share link and a 404 page.
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
  // The quiz screen needs a store joined to that quiz, or showing the results of that quiz after an ended join (which
  // binds no quiz). A direct load, a refresh or another ID goes to the join screen with the ID filled in, like `/q/:quizId`.
  // A reload of the quiz this tab last joined also joins it again: the join screen shows the progress and opens it on `joined`.
  router.beforeEach((to) => {
    if (to.name !== 'quiz') return
    const store = useQuizStore()
    const quizId = String(to.params.quizId)
    if (store.quizId === quizId && (store.quiz !== null || store.ended)) return
    if (store.quizId === null) store.resume(quizId)
    return { name: 'join', query: { quiz: quizId } }
  })
  return router
}
