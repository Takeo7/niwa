// Thin re-exports so feature components don't reach into shared/api
// directly.  Mirrors the features/runs/hooks pattern from PR-10a.
export {
  useApprovals,
  useTaskApprovals,
  useApproval,
  useResolveApproval,
} from '../../../shared/api/queries';
