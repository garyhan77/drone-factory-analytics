import streamlit as st

from factory.viz import analysis_results as ar
from factory.viz import charts
from factory.viz.render import chart, current_palette, page_header

pal = current_palette()
page_header("Causal Analysis & Experiments", "Operations analyst", "Did the emergency fasteners cause the defects, and should we add Avionics capacity?")

causal, logit, wait = ar.load("causal_summary"), ar.load("regression_logit_summary"), ar.load("regression_wait_summary")
results, secondary, guardrail = ar.load("experiment_results"), ar.load("experiment_secondary"), ar.load("experiment_guardrail")

for sentence in ar.analysis_finding(causal, results, guardrail):
    st.markdown(sentence)
st.caption("Computed offline by the analysis/ package (`make analysis`) and read from its saved results; this page runs no models.")

st.subheader("Did the emergency fastener lots cause the failures?")
table = ar.causal_rows(causal)
chart(charts.estimator_chart(table, 100 * ar.TRUE_EFFECT, pal), table, key="estimators",
      caption="Mean estimate over 91 simulated factories, in percentage points of first-pass failure at Motor & Prop. The generator "
      "plants a +19.5 point effect and also swamps inspectors in weeks 11 to 15, the same weeks the emergency lots arrive. "
      "Comparing drones with and without a lot ignores that and overstates the effect; adjusting for the week does not.")
placebo = ar.causal_rows(causal, "AFL")
st.markdown("**Placebo check.** At Airframe, upstream of Motor & Prop, a later fastener lot cannot matter, so the true effect is 0.")
st.dataframe(placebo, hide_index=True, width="stretch")
st.caption("The naive method finds a false effect there too. The adjusted methods find about zero.")

st.subheader("How much does each queued drone add to the wait?")
w = wait.iloc[0]
a, b, c = st.columns(3)
a.metric("Regression slope", f"{w['mean_slope_h']:.2f} h per drone")
b.metric("Implied by throughput", f"{w['mean_implied_h']:.2f} h per drone")
c.metric("Within 15% in", f"{100 * w['share_within_15pct']:.0f}% of runs")
st.caption("Avionics wait regressed on the queue a drone finds on arrival, with standard errors that allow for waits being correlated over "
           "time. The check is a separate calculation: Avionics completes about 26 jobs a week while saturated, so one more queued drone "
           "adds 168 / 26 hours. This is a throughput cross-check, not a planted value.")

st.subheader("Should we add Avionics lanes?")
gains = ar.lane_gains(results)
chart(charts.lane_gain_chart(gains, 25.0, pal), gains.rename(columns={"label": "Added lane", "gain": "Extra drones", "lo": "Interval low", "hi": "Interval high"}).round(1),
      key="lanes", caption="20 simulated 26-week runs, each played under 2, 3 and 4 lanes. The 25-drone bar is an assumption standing in for "
      "what a lane costs. The fourth lane's gain is real but far below it.")
st.dataframe(ar.lane_outcomes(results, secondary), hide_index=True, width="stretch")
worst = guardrail["difference"].max()
st.caption(f"Guardrail: a faster Avionics could just move the queue to Final Test. Its wait rises at most {worst:.1f} hours against a 24-hour limit. "
           "The size of that rise varied between test rounds, so treat it as small but not precisely known.")

with st.expander("What this does not show"):
    st.markdown(
        "- All the data is synthetic. I know the truth because I wrote the generator.\n"
        "- I planted the confounder. Week adjustment works because the confounder is a function of week; real confounders are rarely that visible.\n"
        "- More capacity at a bottleneck raising output is expected. The value is in the design: a pre-set outcome and guardrail, a power analysis on "
        "separate runs, corrected comparisons and an A/A check.\n"
        "- The 25-drone bar is assumed, not derived from costs.\n"
        "- The simulated runs are independent: no interference, novelty effect or peeking.")
