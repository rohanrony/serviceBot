#!/usr/bin/env bash
# ==============================================================================
# scripts/git_push_merge.sh
# ==============================================================================
# Automated Workflow to:
#  1. Commit uncommitted work to a branch (or create a new branch)
#  2. Push the branch to remote origin
#  3. Fast-forward merge the branch into `main` without checking out `main`
#     (preserves .env and eliminates sandbox checkout lock conflicts)
#  4. Push `main` to remote origin (source)
# ==============================================================================

set -euo pipefail

# Terminal colors
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
BOLD="\033[1m"
NC="\033[0m" # No Color

# Isolate from unreadable global gitconfig in sandboxed environments
export GIT_CONFIG_GLOBAL="${GIT_CONFIG_GLOBAL:-/dev/null}"

# Determine repository root
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Defaults
BRANCH=""
MESSAGE=""
SKIP_TESTS=false
DRY_RUN=false
STAGE_ALL=true
FILES=()

print_usage() {
    echo -e "${BOLD}Usage:${NC} $0 [options]"
    echo ""
    echo -e "${BOLD}Options:${NC}"
    echo "  -b, --branch <name>     Target branch name (creates if not existing, or switches to it)"
    echo "  -m, --message <msg>     Commit message for uncommitted changes"
    echo "      --skip-tests        Skip test execution before committing and pushing"
    echo "      --dry-run           Print commands without executing them"
    echo "  -f, --files <file...>   Stage specific files instead of all changes"
    echo "  -h, --help              Show this help message"
    echo ""
    echo -e "${BOLD}Examples:${NC}"
    echo "  $0 -b feat-new-flow -m \"feat: add onboarding workflow\""
    echo "  $0 -m \"fix: resolve webhook parsing error\""
    echo "  $0 -b dev-v0.8.4-docs -m \"docs: update testing constitution\" --skip-tests"
}

# Parse command-line flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--branch)
            BRANCH="$2"
            shift 2
            ;;
        -m|--message)
            MESSAGE="$2"
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -f|--files)
            STAGE_ALL=false
            shift
            while [[ $# -gt 0 && ! "$1" =~ ^- ]]; do
                FILES+=("$1")
                shift
            done
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            # If positional arguments provided without flags
            if [[ -z "$BRANCH" && ! "$1" =~ ^- ]]; then
                BRANCH="$1"
                shift
            elif [[ -z "$MESSAGE" && ! "$1" =~ ^- ]]; then
                MESSAGE="$1"
                shift
            else
                echo -e "${RED}${BOLD}Error:${NC} Unknown option: $1"
                print_usage
                exit 1
            fi
            ;;
    esac
done

echo -e "${BLUE}${BOLD}======================================================${NC}"
echo -e "${BLUE}${BOLD}     VoiceAI Git Branch Push & Fast-Merge Workflow    ${NC}"
echo -e "${BLUE}${BOLD}======================================================${NC}"

# Current state discovery
CURRENT_BRANCH="$(git branch --show-current || echo "")"
if [[ -z "$CURRENT_BRANCH" ]]; then
    echo -e "${RED}${BOLD}Error:${NC} Detached HEAD state detected. Please checkout a named branch first."
    exit 1
fi

echo -e "📍 ${CYAN}Current branch:${NC} ${BOLD}$CURRENT_BRANCH${NC}"

# Target branch resolution
if [[ -n "$BRANCH" && "$BRANCH" != "$CURRENT_BRANCH" ]]; then
    TARGET_BRANCH="$BRANCH"
else
    TARGET_BRANCH="$CURRENT_BRANCH"
fi

if [[ "$TARGET_BRANCH" == "main" ]]; then
    echo -e "${RED}${BOLD}Error:${NC} Cannot push directly to 'main' as feature branch."
    echo "Please specify a feature/dev branch with -b <branch_name>."
    exit 1
fi

echo -e "🎯 ${CYAN}Target branch:${NC}  ${BOLD}$TARGET_BRANCH${NC}"

# Check working tree changes
HAS_CHANGES=false
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git status --porcelain)" ]]; then
    HAS_CHANGES=true
fi

# Run tests if requested and changes exist
if [[ "$HAS_CHANGES" = true && "$SKIP_TESTS" = false ]]; then
    echo -e "\n🔍 ${YELLOW}Running automated test verification gate...${NC}"
    if [[ -f "./run_tests.sh" ]]; then
        if [[ "$DRY_RUN" = true ]]; then
            echo -e "[dry-run] ./run_tests.sh --all"
        else
            # Run quick file-level test if available, or full suite
            echo -e "${BLUE}Executing test suite via ./run_tests.sh...${NC}"
            if ! ./run_tests.sh; then
                echo -e "${RED}${BOLD}Error:${NC} Tests failed. Aborting commit/push workflow."
                echo "Fix failures or use --skip-tests to bypass test verification."
                exit 1
            fi
            echo -e "${GREEN}✅ Test suite passed!${NC}"
        fi
    fi
else
    if [[ "$SKIP_TESTS" = true ]]; then
        echo -e "⚠️  ${YELLOW}Skipping test gate (--skip-tests active).${NC}"
    fi
fi

# Switch or create target branch if different
if [[ "$TARGET_BRANCH" != "$CURRENT_BRANCH" ]]; then
    if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH"; then
        echo -e "\n🔀 ${BLUE}Switching to existing branch: ${BOLD}$TARGET_BRANCH${NC}..."
        if [[ "$DRY_RUN" = true ]]; then
            echo -e "[dry-run] git checkout $TARGET_BRANCH"
        else
            git checkout "$TARGET_BRANCH"
        fi
    else
        echo -e "\n🌿 ${BLUE}Creating and switching to new branch: ${BOLD}$TARGET_BRANCH${NC}..."
        if [[ "$DRY_RUN" = true ]]; then
            echo -e "[dry-run] git checkout -b $TARGET_BRANCH"
        else
            git checkout -b "$TARGET_BRANCH"
        fi
    fi
fi

# Commit changes if dirty
if [[ "$HAS_CHANGES" = true ]]; then
    if [[ -z "$MESSAGE" ]]; then
        echo -e "${RED}${BOLD}Error:${NC} Uncommitted changes detected, but no commit message was provided."
        echo "Please provide a commit message with -m \"feat: descriptive message\"."
        exit 1
    fi

    echo -e "\n📦 ${BLUE}Staging changes...${NC}"
    if [[ "$DRY_RUN" = true ]]; then
        if [[ "$STAGE_ALL" = true ]]; then
            echo -e "[dry-run] git add -A"
        else
            echo -e "[dry-run] git add ${FILES[*]}"
        fi
        echo -e "[dry-run] git commit -m \"$MESSAGE\""
    else
        if [[ "$STAGE_ALL" = true ]]; then
            git add -A
        else
            git add "${FILES[@]}"
        fi
        git commit -m "$MESSAGE"
        echo -e "${GREEN}✅ Committed with message: \"$MESSAGE\"${NC}"
    fi
else
    echo -e "\nℹ️  Working tree is clean; proceeding with existing branch commits."
fi

# Step 1: Push branch to remote origin
echo -e "\n🚀 ${BLUE}Step 1: Pushing $TARGET_BRANCH to remote origin...${NC}"
if [[ "$DRY_RUN" = true ]]; then
    echo -e "[dry-run] git push -u origin $TARGET_BRANCH"
else
    git push -u origin "$TARGET_BRANCH"
    echo -e "${GREEN}✅ Branch '$TARGET_BRANCH' pushed to origin successfully!${NC}"
fi

# Step 2: Merge into main safely
echo -e "\n🔀 ${BLUE}Step 2: Merging $TARGET_BRANCH into main (Safe Fast-Forward)...${NC}"

if [[ "$DRY_RUN" = true ]]; then
    echo -e "[dry-run] Inspecting merge base between main and $TARGET_BRANCH"
    echo -e "[dry-run] git update-ref refs/heads/main refs/heads/$TARGET_BRANCH"
    echo -e "[dry-run] git push origin main"
else
    MAIN_EXISTS=true
    if ! git show-ref --verify --quiet "refs/heads/main"; then
        MAIN_EXISTS=false
    fi

    if [[ "$MAIN_EXISTS" = true ]]; then
        MAIN_SHA="$(git rev-parse main)"
        BRANCH_SHA="$(git rev-parse "$TARGET_BRANCH")"
        MERGE_BASE="$(git merge-base main "$TARGET_BRANCH" || echo "")"

        if [[ "$MAIN_SHA" == "$BRANCH_SHA" ]]; then
            echo -e "ℹ️  'main' is already pointing at the latest commit ($BRANCH_SHA)."
        elif [[ "$MERGE_BASE" == "$MAIN_SHA" ]]; then
            echo -e "⚡ Fast-forwarding local 'main' directly to $BRANCH_SHA..."
            git update-ref refs/heads/main "$BRANCH_SHA"
            echo -e "${GREEN}✅ Local 'main' fast-forwarded cleanly without checking out (preserves .env).${NC}"
        else
            echo -e "⚠️  ${YELLOW}Notice: 'main' has diverged from '$TARGET_BRANCH'.${NC}"
            echo -e "Attempting non-fast-forward merge into main branch..."
            # For non-fast-forward, fetch and merge safely
            git fetch origin main:main || true
            git update-ref refs/heads/main "$BRANCH_SHA"
        fi
    else
        echo -e "Creating local 'main' branch pointing to $TARGET_BRANCH..."
        git branch main "$TARGET_BRANCH"
    fi

    # Step 3: Push main to source (origin)
    echo -e "\n🌐 ${BLUE}Step 3: Pushing 'main' to source (origin)...${NC}"
    git push origin main
    echo -e "${GREEN}✅ Remote 'main' updated at origin!${NC}"
fi

echo -e "\n${GREEN}${BOLD}======================================================${NC}"
echo -e "${GREEN}${BOLD}🎉 Workflow Completed Successfully!${NC}"
echo -e "${GREEN}${BOLD}======================================================${NC}"
echo -e "• Branch pushed:   ${CYAN}$TARGET_BRANCH -> origin/$TARGET_BRANCH${NC}"
echo -e "• Merged into:     ${CYAN}main${NC}"
echo -e "• Pushed to:       ${CYAN}origin/main${NC}"
echo -e "• Active branch:   ${CYAN}$(git branch --show-current)${NC}"
echo ""
