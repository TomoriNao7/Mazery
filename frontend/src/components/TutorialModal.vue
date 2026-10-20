<script setup lang="ts">
import AppModal from './AppModal.vue'

withDefaults(defineProps<{ show: boolean }>(), { show: false })
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <AppModal :show="show" width="640px" title="新手教程" center-title @close="emit('close')">
    <div class="book">
      <div class="book-spine" />
      <div class="book-pages">
        <section class="chapter">
          <div class="chap-no display">第一讲</div>
          <h3 class="chap-title">游戏目标</h3>
          <p>你将扮演剧本里的一名角色，与 AI 扮演的其余角色展开一场完整推理。全流程五幕：<b>介绍 → 搜证 → 交换信息 + 私聊 → 再搜证 → 公聊 + 投票</b>，最后 GM 复盘真相。</p>
          <p>你的目标因身份而异：<b>好人阵营</b>在五幕里集齐线索、判断谁是凶手；<b>真凶</b>则要藏好自己、误导众人，让别人替你背锅。</p>
        </section>

        <section class="chapter">
          <div class="chap-no display">第二讲</div>
          <h3 class="chap-title">角色与信息边界</h3>
          <p>每个角色有自己的：公开身份、隐藏的秘密、知道的信息范围（信息边界）、怀疑对象与情绪压力。</p>
          <p><b>核心规则：只说自己知道的事。</b>AI 角色严格遵守信息边界，绝不剧透、绝不替别人圆场；你扮演时也应如此，否则推理就失去了公平。</p>
        </section>

        <section class="chapter">
          <div class="chap-no display">第三讲</div>
          <h3 class="chap-title">五幕流程速览</h3>
          <ul class="chap-list">
            <li><b>第一幕 · 介绍</b>：彼此自我介绍、互相提问，混个脸熟顺便试探。</li>
            <li><b>第二幕 · 抽卡搜证</b>：从线索池抽取关键词，你和你身边的角色各自发现一条线索。</li>
            <li><b>第三幕 · 交换信息 + 私聊</b>：当众宣读线索（有人会隐瞒、有人会编造），再私下找个别人单聊交易。</li>
            <li><b>第四幕 · 再抽卡搜证</b>：又一批新线索浮出水面，凶手在众人面前越来越难藏。</li>
            <li><b>第五幕 · 交换 + 公聊 + 投票</b>：最后摊牌、公开对质，全员投票指认凶手。</li>
            <li><b>复盘</b>：GM 揭晓真相，回放关键推理链，给这一局打分。</li>
          </ul>
        </section>

        <section class="chapter">
          <div class="chap-no display">第四讲</div>
          <h3 class="chap-title">搜证与线索</h3>
          <p>线索分<b>关键线索</b>（直接指向真凶的证据链环节）与<b>误导线索</b>（看着可疑、实为烟雾弹，或指向无关秘密）。</p>
          <p>当众出示的线索会成为全员可见的公开信息；隐瞒或编造也会有破绽——说过的话被写进记忆，之后私聊、对质都可能被问穿。</p>
        </section>

        <section class="chapter">
          <div class="chap-no display">第五讲</div>
          <h3 class="chap-title">讨论与私聊</h3>
          <p><b>讨论是轮次制</b>：每轮按固定顺序，一个角色一个角色发言，可以<b>提问</b>、<b>陈述</b>、<b>出示线索</b>。AI 只会在中后期针对有公开证据的角色提问，不会一上来就乱指。</p>
          <p><b>私聊只有双方可见</b>：能打探秘密、交换情报、谈交易，但内容不会再当众曝光——除非事后有人拿出来说。</p>
        </section>

        <section class="chapter">
          <div class="chap-no display">第六讲</div>
          <h3 class="chap-title">投票与揭晓</h3>
          <p>第五幕末全员（含 AI 角色）投票指认凶手，票数仅代表"谁最可疑"。之后进入复盘：GM 揭晓真实凶手与手法，回看每条关键线索如何织成证据链，并就你的表现给出评级。</p>
        </section>

        <section class="chapter tip-wrap">
          <div class="chap-no display">第七讲</div>
          <h3 class="chap-title">游玩注意事项</h3>
          <div class="tip"><b>真凶视角</b>：别自曝、别一锤定音；把话题引向误导线索、给怀疑你的人泼回去，但别把话说死，留足周旋余地。</div>
          <div class="tip"><b>好人视角</b>：记录谁说了什么、谁在隐瞒、谁前后矛盾——AI 会说谎，别轻信单条线索。</div>
          <div class="tip"><b>信息不对称</b>：你看到的未必是全部。秘密、动机、不在场证明都可能解释一条线索为什么指向你。</div>
          <div class="tip"><b>别打断</b>：讨论是轮次制，等轮到自己再发言；私聊时可不透露给其他人。</div>
        </section>

        <section class="chapter">
          <div class="chap-no display">第八讲</div>
          <h3 class="chap-title">设置与模型</h3>
          <p>在「设置」页可切换模型与 API Key（支持本地 Ollama 或云端 OpenAI 兼容端点）。<b>生成剧本是多次串行 AI 调用，可能需要几分钟</b>，请耐心等待进度条走完；若生成失败，检查模型是否可用、额度是否充足。</p>
        </section>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.book {
  position: relative;
  max-height: 64vh;
  overflow-y: auto;
  border-radius: 6px;
  background: linear-gradient(180deg, #f6ecd9, #efe2c6);
  color: #2b2418;
  padding: 30px 34px 34px 40px;
  box-shadow:
    inset 30px 0 30px -30px rgba(120, 90, 40, 0.35),
    inset -18px 0 24px -24px rgba(120, 90, 40, 0.28),
    0 14px 40px rgba(0, 0, 0, 0.5);
}
.book-spine {
  position: absolute;
  left: 18px;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(90deg, rgba(120, 90, 40, 0.35), transparent);
}
.book-pages {
  font-family: var(--font-body);
}
.chapter {
  margin-bottom: 24px;
}
.chap-no {
  font-size: 12px;
  letter-spacing: 0.24em;
  color: #9a7b3f;
  margin-bottom: 4px;
}
.chap-title {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 8px;
  letter-spacing: 0.04em;
  color: #2b2418;
}
.chapter p {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.85;
}
.chap-list {
  margin: 0;
  padding: 0 0 0 20px;
}
.chap-list li {
  font-size: 13px;
  line-height: 1.85;
  margin-bottom: 4px;
}
.tip-wrap .chap-title {
  margin-bottom: 14px;
}
.tip {
  border: 1px solid rgba(154, 123, 63, 0.5);
  background: rgba(154, 123, 63, 0.12);
  border-radius: 8px;
  padding: 10px 13px;
  margin-bottom: 10px;
  font-size: 13px;
  line-height: 1.75;
}
</style>