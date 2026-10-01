// AI-ASSISTED: client entry: Pinia, the router and the global styles.
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { createAppRouter } from './router'
import 'vue-sonner/style.css'
import './styles/main.css'

createApp(App).use(createPinia()).use(createAppRouter()).mount('#app')
