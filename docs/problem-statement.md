# Problem Statement

> **A note on evidence:** this repository does not contain verified quantitative data about
> real clinical trials, deviation rates or monitoring costs. The motivation below is
> therefore **qualitative**. We have deliberately not included invented statistics.

## Background

A clinical trial tests a treatment by following a written **protocol**: the rules every
participating site must follow. A protocol says, for example, when each patient visit must
happen (with an allowed window of days), what dose must be given, and which other
medications are not allowed.

Larger trials run at many **sites** (hospitals or clinics), each enrolling many patients,
each with several scheduled visits. That quickly becomes a large number of visit records to
check.

## The Problem

A **protocol deviation** is any departure from those rules, for example:

- a visit that is **missed** or happens **outside its allowed window**,
- a patient given the **wrong dose**,
- a patient taking a **prohibited medication**,
- a visit where required information is **not documented**.

Deviations can go unnoticed for a long time, sometimes until an audit. Even when they are
found, they usually appear as a **flat list of individual errors**. A list like that does
not answer the questions a monitor actually has:

1. **Which sites need attention first?**
2. **Why** is a site risky — is it one-off mistakes or a repeating process problem?
3. **Is it getting worse** over the course of the study?
4. **What should be done** about it?

## Who is Affected

- **Primary audience — clinical trial monitors and quality staff** (for example, clinical
  research associates or central monitoring teams) who review data from many sites and
  must decide where to focus visits, calls and retraining.
- **Site staff**, who benefit from finding a process problem early rather than repeating it
  for many patients.
- **Patients**, because wrong doses and prohibited medications are safety concerns, and
  missed visits can mean missed safety checks.
- **Sponsors and study teams**, because widespread deviations can weaken confidence in a
  trial's data.

## Why It Matters

- **Safety:** dosing errors and prohibited medications directly affect patients.
- **Data quality:** missed or badly timed visits mean data is collected at the wrong time or
  not at all.
- **Patterns matter more than single events:** one late visit may be harmless; the same
  mistake repeated across several patients at one site suggests a process problem (for
  example, how doses are checked or how visits are scheduled). Spotting the pattern is what
  makes a corrective action possible.
- **Early warning matters:** a site whose deviations increase at later visits may still look
  acceptable in a total count today. Seeing the trend early gives time to act before the
  problem grows.
- **Actions, not just alerts:** knowing a site is risky is only useful if it leads to a
  sensible next step — the purpose of a CAPA (Corrective and Preventive Action) plan.

## Why Existing / Basic Approaches Fall Short

We did not evaluate specific commercial products for this prototype, so we describe basic
approaches in general terms:

- **Manual review of spreadsheets or listings** is slow when there are many sites and
  visits, and it is easy to miss a pattern that is spread across several patients.
- **Simple rule checks** (for example, "flag any wrong dose") produce lists of individual
  deviations, but not a **site-level** picture of risk.
- **A single total count per site** hides important information: it treats a
  documentation gap like a wrong dose, penalises large sites for having more patients, and
  does not show whether things are getting worse.
- **Separate tools** for finding deviations, judging severity, tracking trends and writing
  action plans make it hard to see the whole story for one site in one place.

TrialGuard explores what an **integrated, transparent view** could look like: detection,
severity, site risk, early warnings and suggested actions together, with every result
traceable to a readable rule.

> TrialGuard is a hackathon proof-of-concept using synthetic data. It is not intended for
> real clinical or regulatory decisions.
