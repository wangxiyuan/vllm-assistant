<script setup lang="ts">
import Sidebar from './Sidebar.vue'
import MobileSidebar from './MobileSidebar.vue'
import Header from './Header.vue'
import DailyReportBanner from '@/components/common/DailyReportBanner.vue'
</script>

<template>
  <div class="app-shell">
    <Sidebar />
    <MobileSidebar />
    <Header />
    <main class="main">
      <DailyReportBanner />
      <router-view />
    </main>
  </div>
</template>
