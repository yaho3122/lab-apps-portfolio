# ProjectFlow Application Usage Guide

This document provides instructions on how to use the ProjectFlow application, including details on how key metrics are calculated and how task information is utilized.

## 1. Overview

ProjectFlow is a web-based application designed to track the progress of transformation projects. It provides a calendar view, a Gantt chart view, and a dashboard for visualizing project timelines and key performance indicators (KPIs).

## 2. Dashboard Metrics

The dashboard displays several important metrics that are calculated based on the data you input into the project tasks.

### Data Input for Calculations

The primary data for the `TF%` and `Regen #` calculations is derived from the **description field** of the **Pre** task in a project's workflow.

The data must be entered in the following format:

`V1,V2,V3`

For example: `500,250,50`

-   **V1**: The total number of explants used.
-   **V2**: The number of transformed explants.
-   **V3**: The number of regenerated plants.

### TF% (Transformation Frequency)

The Transformation Frequency is a percentage that represents the efficiency of the transformation process. It is calculated using the `V1` and `V2` values from the "Pre" task description.

-   **Formula:** `TF% = (V2 / V1) * 100`

**Example:**
If the "Pre" task description is `500,250,50`:
-   V1 = 500
-   V2 = 250
-   TF% = (250 / 500) * 100 = 50%

### Regen # (Regeneration Number)

The Regeneration Number represents the total count of regenerated plants from a project. This value is automatically calculated and updated based on the information you provide in the **RS** task.

-   **Calculation:** The `Regen #` is the total number of lines entered into the description of the **RS** task. Each line represents a unique regenerated plant or event.

When you add or remove lines in the "RS" task description, the application automatically updates the `V3` value in the corresponding "Pre" task, which is then reflected on the dashboard as the `Regen #`.

## 3. Task Descriptions and the Dashboard

The information you provide in the task descriptions is used to populate the dashboard and other views, giving a clear overview of each project.

-   **Project Name and Description**: The `Project Name` and `Project Description` displayed on the dashboard are taken directly from the **Start** task of the workflow.

-   **Pre, RS, and Transformation Task Information**: The data and descriptions entered into these tasks are crucial for the calculations and for providing context to the project's progress. The dates and descriptions are visible in the calendar and Gantt views, allowing for a detailed chronological tracking of all activities.

By keeping the information in these tasks accurate and up-to-date, you ensure that the dashboard and all project views provide a reliable and meaningful representation of your work.
