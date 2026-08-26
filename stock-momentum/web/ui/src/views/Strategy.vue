<script setup>
import { computed } from "vue";
import { store } from "../store.js";
const h = computed(() => store.state?.health || {});
</script>

<template>
  <div class="page">
    <div><span class="tag">Reference</span><h1>What this thing does</h1></div>

    <section class="hud body">
      <p class="lede big">Once a month it ranks forty large American companies by
        how much they rose over six months, ignoring the most recent month, and
        holds the top eight in equal amounts. That is the whole idea.</p>

      <h2>Why skip the last month</h2>
      <p>Shares that jump hard tend to give some of it back over the following
        weeks. Ranking on the six months <em>ending a month ago</em> steps around
        that reversal, and it is the difference between a rule that works and one
        that does not.</p>

      <h2>Why eight</h2>
      <p>Fewer names means the ranking matters more and one bad pick hurts more.
        Eight of forty is concentrated enough that the ranking drives the result,
        spread enough that no single company decides your year.</p>

      <h2>The part worth deciding in advance</h2>
      <p>The worst stretch in the backtest was a <b class="down">59.7% drawdown</b>
        bottoming in March 2009 — deeper than the index fell. The account did not
        regain its December 2007 high until May 2013. Five and a half years of
        opening this page and seeing a number lower than one you already had.</p>
      <p>2009 is the specific weakness: the strategy made 9% while the index made
        23.5%, because coming off the bottom the best six-month records belonged
        to the defensive names that had fallen least. Momentum buys what has
        already worked, which is exactly the wrong thing to hold on the day the
        market turns. That is not a bug that got fixed.</p>

      <h2>How the money moves</h2>
      <p>Total the whole account, divide by eight, make every position that size.
        A stock you sell at a profit does not fund its replacement — the gain
        spreads across all eight, which is why every position grows together.</p>

      <h2>Paper and Trading 212</h2>
      <p>The paper book simulates the strategy on assumed fills and keeps running
        whatever else happens. The live book mirrors Trading 212. The gap between
        them is your execution: slippage, currency fees, an order placed late.
        Without both you could not tell a bad month from a badly executed one.</p>

      <h2>What the backtest cannot tell you</h2>
      <p>The forty names were chosen in 2026, so every historical figure is
        flattered by knowing which companies survived. Holding all forty and never
        trading beat the strategy over twenty-one years — but 41% of that was
        NVIDIA alone, and nobody picking a list in 2005 would have held it through
        an 85% fall. Against the index, which you could actually have bought,
        $1,000 became $36,110 versus $6,233.</p>

      <p class="fine mode">Trading the
        <b>{{ h.track === "live" ? "Trading 212" : "paper" }}</b> book.</p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; max-width: 760px ; margin: 0 auto }
.body { padding: 26px 30px; display: flex; flex-direction: column; gap: 14px }
.body p { max-width: 66ch; color: var(--body) }
.lede.big { font-size: 1.05rem; color: var(--ink) }
h2 { margin-top: 10px; color: var(--cyan); font-size: .82rem;
  letter-spacing: .14em; text-transform: uppercase; font-family: var(--f-mono);
  font-weight: 500 }
.mode { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--hair) }
</style>
