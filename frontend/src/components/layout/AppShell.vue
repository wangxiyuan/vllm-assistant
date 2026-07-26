<script setup lang="ts">
import Sidebar from './Sidebar.vue'
import MobileSidebar from './MobileSidebar.vue'
import Header from './Header.vue'
</script>

<template>
  <div class="app-shell">
    <Sidebar />
    <MobileSidebar />
    <Header />
    <main class="main">
      <router-view />
    </main>
  </div>
</template>
