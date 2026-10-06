type Task = { id: string; status: string };

export async function runWorkspaceTask({ task, activePath, createTask, resumeTask, showDiff }: {
  task: Task | null;
  activePath: string | null;
  createTask: (objective: string) => Promise<void>;
  resumeTask: () => Promise<void>;
  showDiff: () => void;
}): Promise<string | null> {
  if (!task || ['completed', 'cancelled', 'failed'].includes(task.status)) {
    if (!activePath) return 'Select a file or enter a task objective in RLB AI before running.';
    await createTask(`Verify execution of the selected workspace file ${JSON.stringify(activePath)}. Use the existing planning, human approval, staging, testing and reviewer workflow. Preserve the application behavior, run the file with the appropriate local toolchain during testing, and retain its stdout, stderr and exit status as task evidence. Do not skip approval gates.`);
    return null;
  }
  if (task.status === 'plan_review') return 'Review and approve the plan in RLB AI before execution can continue.';
  if (task.status === 'code_review') {
    showDiff();
    return 'Review the staged changes before execution can continue.';
  }
  await resumeTask();
  return null;
}
