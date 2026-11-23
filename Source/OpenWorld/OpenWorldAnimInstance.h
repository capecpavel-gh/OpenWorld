// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "OpenWorldAnimInstance.generated.h"

class UAnimSequence;

/**
 *  Evaluates the Anim Blueprint graph and then blends an "overlay" animation on top of it:
 *  fully on the upper body, and on the lower body only as far as LowerBodyWeight says.
 */
USTRUCT()
struct FOpenWorldAnimInstanceProxy : public FAnimInstanceProxy
{
	GENERATED_BODY()

	FOpenWorldAnimInstanceProxy() = default;
	explicit FOpenWorldAnimInstanceProxy(UAnimInstance* Instance) : FAnimInstanceProxy(Instance) {}

protected:

	virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
	virtual bool Evaluate_WithRoot(FPoseContext& Output, FAnimNode_Base* InRootNode) override;

private:

	void ApplyOverlay(FPoseContext& Output);
	void UpdateBoneMask(const FBoneContainer& Bones);

	// Copied from the anim instance on the game thread; the instance keeps the sequences alive.
	const UAnimSequence* Sequence = nullptr;
	const UAnimSequence* PreviousSequence = nullptr;
	float Time = 0.f;
	float PreviousTime = 0.f;
	float CrossfadeAlpha = 1.f;
	float Weight = 0.f;
	float LowerBodyWeight = 0.f;
	FName UpperBodyRootBone;

	/** Per compact-pose bone: 1 if the bone belongs to the upper body */
	TArray<uint8> UpperBodyMask;
	FName MaskRootBone;
	uint16 MaskSerialNumber = 0;
};

/**
 *  Anim instance base class for the player character's Anim Blueprint.
 *  Lets C++ play an animation over the locomotion: the upper body always follows it,
 *  the legs follow it only while the character stands still, so attacking does not stop running.
 */
UCLASS()
class UOpenWorldAnimInstance : public UAnimInstance
{
	GENERATED_BODY()

public:

	/** Plays an animation on top of the Anim Blueprint's pose. Calling it while one is playing cross-fades into the new one. */
	UFUNCTION(BlueprintCallable, Category="Overlay")
	void PlayOverlay(UAnimSequence* Sequence, float BlendInTime = 0.1f, float BlendOutTime = 0.22f);

	/** Fades the current overlay animation out */
	UFUNCTION(BlueprintCallable, Category="Overlay")
	void StopOverlay(float BlendOutTime = 0.15f);

	UFUNCTION(BlueprintPure, Category="Overlay")
	bool IsOverlayPlaying() const { return OverlaySequence != nullptr; }

	/** Current time in the overlay animation [s] */
	UFUNCTION(BlueprintPure, Category="Overlay")
	float GetOverlayTime() const { return OverlayTime; }

protected:

	/** This bone and everything below it always follows the overlay animation */
	UPROPERTY(EditAnywhere, Category="Overlay")
	FName UpperBodyRootBone = TEXT("spine_01");

	/** Below this speed the legs and hips follow the overlay animation too */
	UPROPERTY(EditAnywhere, Category="Overlay", meta=(ClampMin="0", Units="cm/s"))
	float FullBodyMaxSpeed = 20.f;

	/** How quickly the legs switch between the overlay animation and locomotion */
	UPROPERTY(EditAnywhere, Category="Overlay", meta=(ClampMin="0"))
	float LowerBodyBlendSpeed = 8.f;

	virtual void NativeUpdateAnimation(float DeltaSeconds) override;
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;

private:

	friend struct FOpenWorldAnimInstanceProxy;

	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> OverlaySequence;

	/** Overlay that was playing when a new one started; held at PreviousOverlayTime during the cross-fade */
	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> PreviousOverlaySequence;

	float OverlayTime = 0.f;
	float OverlayWeight = 0.f;
	float OverlayBlendIn = 0.1f;
	float OverlayBlendOut = 0.22f;
	float OverlayStartWeight = 0.f;
	float PreviousOverlayTime = 0.f;
	float CrossfadeAlpha = 1.f;
	float LowerBodyWeight = 1.f;
};
