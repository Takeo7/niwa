import { Button, Group, NumberInput, Select, Stack, Switch, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";

import type {
  AutonomyMode,
  DeployTrigger,
  DeployType,
  PlanApprovalMode,
  Project,
} from "../../api";
import { usePatchProject } from "./api";

interface Props {
  project: Project;
}

export function ProjectSettingsTab({ project }: Props) {
  const patchProject = usePatchProject(project.slug);
  const [autonomyMode, setAutonomyMode] = useState<AutonomyMode>(project.autonomy_mode);
  const [deployTrigger, setDeployTrigger] = useState<DeployTrigger>(project.deploy_trigger);
  const [planApprovalMode, setPlanApprovalMode] = useState<PlanApprovalMode>(
    project.plan_approval_mode,
  );
  const [maxReviewIterations, setMaxReviewIterations] = useState(
    project.max_review_iterations,
  );
  const [deployType, setDeployType] = useState<DeployType>(project.deploy_type);
  const [publicEnabled, setPublicEnabled] = useState(project.public_enabled);
  const [gitRemote, setGitRemote] = useState(project.git_remote ?? "");
  const [distDir, setDistDir] = useState(project.dist_dir ?? "");
  const [startCommand, setStartCommand] = useState(project.start_command ?? "");
  const [healthcheckPath, setHealthcheckPath] = useState(project.healthcheck_path ?? "/");

  useEffect(() => {
    setAutonomyMode(project.autonomy_mode);
    setDeployTrigger(project.deploy_trigger);
    setPlanApprovalMode(project.plan_approval_mode);
    setMaxReviewIterations(project.max_review_iterations);
    setDeployType(project.deploy_type);
    setPublicEnabled(project.public_enabled);
    setGitRemote(project.git_remote ?? "");
    setDistDir(project.dist_dir ?? "");
    setStartCommand(project.start_command ?? "");
    setHealthcheckPath(project.healthcheck_path ?? "/");
  }, [project]);

  const save = () => {
    patchProject.mutate(
      {
        autonomy_mode: autonomyMode,
        deploy_trigger: deployTrigger,
        plan_approval_mode: planApprovalMode,
        max_review_iterations: maxReviewIterations,
        deploy_type: deployType,
        public_enabled: publicEnabled,
        git_remote: gitRemote.trim() || null,
        dist_dir: distDir.trim() || null,
        start_command: startCommand.trim() || null,
        healthcheck_path: healthcheckPath.trim() || null,
      },
      {
        onSuccess: () => {
          notifications.show({
            title: "Settings saved",
            message: project.name,
            color: "green",
          });
        },
        onError: (error) => {
          notifications.show({
            title: "Settings not saved",
            message: error.message,
            color: "red",
          });
        },
      },
    );
  };

  return (
    <Stack gap="md" maw={720}>
      <Stack gap="sm">
        <Title order={4}>Execution</Title>
        <Group grow align="end">
          <Select
            label="Autonomy"
            data={[
              { value: "safe", label: "safe" },
              { value: "dangerous", label: "dangerous" },
            ]}
            value={autonomyMode}
            onChange={(value) => setAutonomyMode((value ?? "safe") as AutonomyMode)}
          />
          <Select
            label="Deploy trigger"
            data={[
              { value: "manual", label: "manual" },
              { value: "on_done", label: "on_done" },
              { value: "on_merge", label: "on_merge" },
            ]}
            value={deployTrigger}
            onChange={(value) => setDeployTrigger((value ?? "manual") as DeployTrigger)}
          />
        </Group>
        <Group grow align="end">
          <Select
            label="Plan approval"
            data={[
              { value: "auto", label: "auto" },
              { value: "manual", label: "manual" },
            ]}
            value={planApprovalMode}
            onChange={(value) => setPlanApprovalMode((value ?? "auto") as PlanApprovalMode)}
          />
          <NumberInput
            label="Review retries"
            min={0}
            max={5}
            value={maxReviewIterations}
            onChange={(value) => setMaxReviewIterations(Number(value) || 0)}
          />
        </Group>
      </Stack>

      <Stack gap="sm">
        <Title order={4}>Deployment</Title>
        <Group grow align="end">
          <Select
            label="Deploy type"
            data={[
              { value: "static", label: "static" },
              { value: "process", label: "process" },
            ]}
            value={deployType}
            onChange={(value) => setDeployType((value ?? "static") as DeployType)}
          />
          <TextInput
            label="Healthcheck path"
            value={healthcheckPath}
            onChange={(event) => setHealthcheckPath(event.currentTarget.value)}
          />
        </Group>
        <TextInput
          label="Dist dir"
          placeholder="dist"
          value={distDir}
          onChange={(event) => setDistDir(event.currentTarget.value)}
        />
        <TextInput
          label="Start command"
          placeholder="npm run start"
          value={startCommand}
          onChange={(event) => setStartCommand(event.currentTarget.value)}
        />
        <Switch
          label="Public deployment"
          checked={publicEnabled}
          onChange={(event) => setPublicEnabled(event.currentTarget.checked)}
        />
      </Stack>

      <Stack gap="sm">
        <Title order={4}>Repository</Title>
        <TextInput
          label="Git remote"
          placeholder="https://github.com/org/repo.git"
          value={gitRemote}
          onChange={(event) => setGitRemote(event.currentTarget.value)}
        />
      </Stack>

      <Group justify="flex-end">
        <Button onClick={save} loading={patchProject.isPending}>
          Save settings
        </Button>
      </Group>
    </Stack>
  );
}
